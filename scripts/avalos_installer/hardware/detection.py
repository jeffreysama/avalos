"""
hardware/detection.py — detección de hardware del instalador de AvalOS.

Extraído de skill_instalar_usb.py (líneas 160-170 y 517-616 de la versión
actual en main). Lógica sin cambios respecto al original — solo se movió
de lugar y se le puso el import de `run_command` desde core.shell en vez
de la `_ejecutar` privada del monolito.
"""

from __future__ import annotations

from pathlib import Path

from avalos_installer.core.shell import run_command

# ── Paquetes de driver recomendados por vendor de GPU ───────────────────
# (Sin cambios respecto al original — mismas listas, mismo orden.)

DRIVER_PKGS_AMD = [
    "mesa", "mesa-utils", "vulkan-radeon", "vulkan-icd-loader", "vulkan-tools",
    "libva-mesa-driver", "libva-utils", "radeontop", "gst-plugin-va",
    "libva", "lib32-mesa", "lib32-vulkan-radeon",
]

DRIVER_PKGS_INTEL = [
    "mesa", "mesa-utils", "vulkan-intel", "vulkan-icd-loader", "vulkan-tools",
    "intel-media-driver", "libva-intel-driver", "libva-utils", "libva",
    "gst-plugin-va", "lib32-mesa", "lib32-vulkan-intel",
]


def is_uefi() -> bool:
    return Path("/sys/firmware/efi").exists()


def detect_microcode() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            c = f.read().lower()
        # Se decide por la línea vendor_id: buscar "intel"/"amd" en TODO el archivo
        # también matchea nombres de flags, modelo, etc. El substring queda de respaldo.
        vendor = next((ln.split(":", 1)[1].strip() for ln in c.splitlines()
                       if ln.startswith("vendor_id") and ":" in ln), "")
        if vendor == "genuineintel":
            return "intel-ucode"
        if vendor == "authenticamd":
            return "amd-ucode"
        if "genuineintel" in c or "intel" in c:
            return "intel-ucode"
        if "authenticamd" in c or "amd" in c:
            return "amd-ucode"
    except OSError:
        pass
    return ""


def detect_cpu_arch_level() -> str:
    """Detecta el nivel de arquitectura x86: v2, v3, v4."""
    try:
        with open("/proc/cpuinfo") as f:
            flags = ""
            for line in f:
                if line.startswith("flags"):
                    flags = line.split(":", 1)[1].lower()
                    break
        flag_set = set(flags.split())
        # /proc/cpuinfo NO tiene flag "lzcnt": el kernel lo expone como "abm"
        # (X86_FEATURE_ABM = CPUID 0x80000001 ECX bit 5 = LZCNT). Con "lzcnt" en el set,
        # v3 nunca se cumplía: toda CPU v3 SIN AVX-512 (Ryzen 1000-5000, Intel de escritorio
        # sin AVX-512...) caía a v2, recibía linux-avalos-compat y se le negaba el kernel BORE.
        # Solo las CPU con AVX-512 (v4) escapaban, porque v4 no mira v3.
        if "lzcnt" in flag_set:
            flag_set.add("abm")
        v4 = {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}
        v3 = {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave"}
        v2 = {"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"}
        if v4.issubset(flag_set) and v3.issubset(flag_set):
            return "x86-64-v4"
        elif v3.issubset(flag_set):
            return "x86-64-v3"
        elif v2.issubset(flag_set):
            return "x86-64-v2"
        else:
            return "x86-64"
    except Exception:
        return "x86-64"


def _parse_lspci_model(line: str) -> str:
    """Extrae el nombre del modelo de una línea de lspci -mm."""
    parts = [p.strip('"') for p in line.split('"') if p.strip('"')]
    return parts[5] if len(parts) > 5 else parts[-1] if parts else "Desconocido"


def detect_gpu() -> dict:
    """Detecta el vendor de GPU via /proc o lspci. Devuelve vendor + pkgs recomendados."""
    try:
        rc, out, _ = run_command(["lspci", "-mm"])
        if rc == 0 and out:
            amd_keywords = ["advanced micro devices", "amd/ati", "radeon", "navi",
                            "polaris", "vega", "rdna", "gfx"]
            intel_keywords = ["intel corporation", "intel xe", "iris xe",
                              "uhd graphics", "hd graphics"]
            gpu_lines = [ln for ln in out.splitlines()
                         if any(k in ln.lower() for k in ("vga", "display", "3d controller"))]
            # Dos pasadas: si hay alguna GPU AMD gana sobre Intel. Antes valía el orden de
            # lspci, y en un portátil con iGPU Intel (00:02.0, sale primero) + dGPU Radeon
            # se instalaban solo los drivers Intel: la GPU con la que se juega quedaba sin
            # vulkan-radeon.
            for line in gpu_lines:
                if any(k in line.lower() for k in amd_keywords):
                    return {"vendor": "amd", "model": _parse_lspci_model(line),
                            "pkgs": DRIVER_PKGS_AMD}
            for line in gpu_lines:
                if any(k in line.lower() for k in intel_keywords):
                    return {"vendor": "intel", "model": _parse_lspci_model(line),
                            "pkgs": DRIVER_PKGS_INTEL}
    except Exception as e:
        print(f"[WARN] detect_gpu lspci: {e}")

    try:
        for vendor_file in Path("/sys/class/drm").glob("card*/device/vendor"):
            vid = vendor_file.read_text().strip()
            if vid == "0x1002":
                return {"vendor": "amd", "model": "AMD GPU", "pkgs": DRIVER_PKGS_AMD}
            if vid == "0x8086":
                return {"vendor": "intel", "model": "Intel GPU", "pkgs": DRIVER_PKGS_INTEL}
    except Exception as e:
        print(f"[WARN] detect_gpu /sys/class/drm: {e}")

    return {"vendor": "amd", "model": "GPU desconocida (asumiendo AMD)", "pkgs": DRIVER_PKGS_AMD}
