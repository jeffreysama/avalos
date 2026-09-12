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
        v4 = {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}
        v3 = {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "lzcnt", "movbe", "xsave"}
        if v4.issubset(flag_set):
            return "x86-64-v4"
        elif v3.issubset(flag_set):
            return "x86-64-v3"
        else:
            return "x86-64-v2"
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
            for line in out.splitlines():
                line_lower = line.lower()
                if "vga" in line_lower or "display" in line_lower or "3d controller" in line_lower:
                    if any(k in line_lower for k in amd_keywords):
                        return {"vendor": "amd", "model": _parse_lspci_model(line),
                                "pkgs": DRIVER_PKGS_AMD}
                    if any(k in line_lower for k in intel_keywords):
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
