import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    // ── Tokyo Night palette ───────────────────────────────────────
    readonly property color c_bg:     "#1a1b26"
    readonly property color c_card:   "#24283b"
    readonly property color c_input:  "#1f2335"
    readonly property color c_hover:  "#292e42"
    readonly property color c_fg:     "#c0caf5"
    readonly property color c_dim:    "#565f89"
    readonly property color c_blue:   "#7aa2f7"
    readonly property color c_purple: "#bb9af7"
    readonly property color c_red:    "#f7768e"
    readonly property color c_border: "#414868"
    readonly property string c_font:  "JetBrainsMono Nerd Font, monospace"

    property bool loginFailed: false

    // ── Fondo ─────────────────────────────────────────────────────
    Rectangle { anchors.fill: parent; color: c_bg }

    // ── Tarjeta central ──────────────────────────────────────────
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: 360
        height: col.implicitHeight + 56
        radius: 12
        color: c_card
        border.color: loginFailed ? c_red : c_border
        border.width: 1

        Behavior on border.color { ColorAnimation { duration: 250 } }

        // Barra de acento superior (blue → purple)
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 2; radius: 2
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0;  color: "transparent" }
                GradientStop { position: 0.2;  color: c_blue        }
                GradientStop { position: 0.8;  color: c_purple      }
                GradientStop { position: 1.0;  color: "transparent" }
            }
        }

        ColumnLayout {
            id: col
            anchors {
                top: parent.top; left: parent.left; right: parent.right
                margins: 24; topMargin: 28
            }
            spacing: 14

            // ── Logo ──────────────────────────────────────────────
            Text {
                Layout.fillWidth: true
                text: "AvalOS"
                horizontalAlignment: Text.AlignHCenter
                font { pixelSize: 28; bold: true; family: c_font }
                color: c_blue
            }

            // ── Reloj + hostname ──────────────────────────────────
            Text {
                id: clockText
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                font { pixelSize: 12; family: c_font }
                color: c_dim
                Timer {
                    interval: 1000; running: true; repeat: true
                    onTriggered: clockText.text =
                        Qt.formatDateTime(new Date(), "hh:mm") +
                        "  \u00b7  " + sddm.hostName +
                        "  \u00b7  " + Qt.formatDateTime(new Date(), "ddd d MMM")
                }
                Component.onCompleted: text =
                    Qt.formatDateTime(new Date(), "hh:mm") +
                    "  \u00b7  " + sddm.hostName +
                    "  \u00b7  " + Qt.formatDateTime(new Date(), "ddd d MMM")
            }

            // ── Separador ─────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true; height: 1
                color: c_border; opacity: 0.5
                Layout.topMargin: 2; Layout.bottomMargin: 2
            }

            // ── Campo usuario ─────────────────────────────────────
            TextField {
                id: userField
                Layout.fillWidth: true
                text: sddm.lastUser
                placeholderText: "%%SDDM_USER%%"
                font { pixelSize: 13; family: c_font }
                color: c_fg
                placeholderTextColor: c_dim
                selectionColor: c_blue
                selectedTextColor: c_bg
                leftPadding: 12
                background: Rectangle {
                    radius: 6; color: c_input
                    border.color: userField.activeFocus ? c_blue : c_border
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 150 } }
                }
                Keys.onTabPressed:   passField.forceActiveFocus()
                Keys.onReturnPressed: passField.forceActiveFocus()
            }

            // ── Campo contraseña ──────────────────────────────────
            TextField {
                id: passField
                Layout.fillWidth: true
                placeholderText: "%%SDDM_PASS%%"
                echoMode: TextInput.Password
                font { pixelSize: 13; family: c_font }
                color: c_fg
                placeholderTextColor: c_dim
                selectionColor: c_blue
                selectedTextColor: c_bg
                leftPadding: 12
                rightPadding: 44
                background: Rectangle {
                    radius: 6; color: c_input
                    border.color: passField.activeFocus ? c_blue : c_border
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 150 } }

                    // Toggle mostrar/ocultar
                    Rectangle {
                        anchors {
                            right: parent.right; rightMargin: 2
                            verticalCenter: parent.verticalCenter
                        }
                        width: 36; height: parent.height - 4; radius: 5
                        color: eyeArea.containsMouse ? c_hover : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Text {
                            anchors.centerIn: parent
                            text: passField.echoMode === TextInput.Normal ? "\u2731" : "\u00b7\u00b7\u00b7"
                            color: c_dim
                            font.pixelSize: passField.echoMode === TextInput.Normal ? 14 : 11
                        }
                        MouseArea {
                            id: eyeArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: passField.echoMode =
                                (passField.echoMode === TextInput.Password)
                                    ? TextInput.Normal : TextInput.Password
                        }
                    }
                }
                Keys.onTabPressed:    userField.forceActiveFocus()
                Keys.onReturnPressed: root.doLogin()
            }

            // ── Botón Sign In ─────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true
                height: 40; radius: 6
                color: signArea.pressed       ? Qt.darker(c_blue, 1.25)
                     : signArea.containsMouse ? Qt.lighter(c_blue, 1.08)
                     : c_blue
                Behavior on color { ColorAnimation { duration: 130 } }
                Text {
                    anchors.centerIn: parent
                    text: "%%SDDM_SIGNIN%%"
                    font { pixelSize: 14; bold: true; family: c_font }
                    color: c_bg
                }
                MouseArea {
                    id: signArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.doLogin()
                }
            }

            // ── Error ─────────────────────────────────────────────
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: "%%SDDM_FAIL%%"
                font { pixelSize: 12; family: c_font }
                color: c_red
                visible: loginFailed
                opacity: loginFailed ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 200 } }
            }

            // ── Separador ─────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true; height: 1
                color: c_border; opacity: 0.4
                Layout.topMargin: 2; Layout.bottomMargin: 2
            }

            // ── Selector de sesión ────────────────────────────────
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "%%SDDM_SESSION%%"
                    font { pixelSize: 11; family: c_font }
                    color: c_dim
                }
                ComboBox {
                    id: sessionCombo
                    Layout.fillWidth: true
                    model: sessionModel
                    textRole: "name"
                    currentIndex: sessionModel.lastIndex
                    font { pixelSize: 12; family: c_font }
                    contentItem: Text {
                        leftPadding: 8
                        text: sessionCombo.displayText
                        font: sessionCombo.font
                        color: c_fg
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        radius: 6; color: c_input
                        border.color: sessionCombo.popup.visible ? c_blue : c_border
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 150 } }
                    }
                    indicator: Text {
                        x: sessionCombo.width - width - 8
                        y: (sessionCombo.height - height) / 2
                        text: sessionCombo.popup.visible ? "\u25b4" : "\u25be"
                        font.pixelSize: 9
                        color: c_dim
                    }
                    popup: Popup {
                        y: sessionCombo.height + 2
                        width: sessionCombo.width
                        implicitHeight: Math.min(contentItem.implicitHeight, 180) + 4
                        padding: 2
                        background: Rectangle {
                            radius: 6; color: c_card
                            border.color: c_border; border.width: 1
                        }
                        contentItem: ListView {
                            clip: true
                            model: sessionCombo.popup.visible ? sessionCombo.delegateModel : null
                            implicitHeight: contentHeight
                        }
                    }
                    delegate: ItemDelegate {
                        id: sessItem
                        width: sessionCombo.width - 4
                        height: 30
                        contentItem: Text {
                            leftPadding: 8
                            text: model.name || ""
                            font { pixelSize: 12; family: c_font }
                            color: sessionCombo.currentIndex === index ? c_blue : c_fg
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: 4
                            color: sessItem.hovered ? c_hover : "transparent"
                        }
                    }
                }
            }

            // ── Botones de energía ────────────────────────────────
            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 4
                spacing: 8

                Item { Layout.fillWidth: true }

                Rectangle {
                    width: 78; height: 28; radius: 6
                    visible: sddm.canSuspend
                    color: suspArea.containsMouse ? c_hover : "transparent"
                    border.color: c_border; border.width: 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors.centerIn: parent
                        text: "%%SDDM_SUSPEND%%"
                        color: c_dim
                        font { pixelSize: 11; family: c_font }
                    }
                    MouseArea {
                        id: suspArea; anchors.fill: parent
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: sddm.suspend()
                    }
                }

                Rectangle {
                    width: 78; height: 28; radius: 6
                    visible: sddm.canReboot
                    color: rstArea.containsMouse ? c_hover : "transparent"
                    border.color: c_border; border.width: 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors.centerIn: parent
                        text: "%%SDDM_RESTART%%"
                        color: c_dim
                        font { pixelSize: 11; family: c_font }
                    }
                    MouseArea {
                        id: rstArea; anchors.fill: parent
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: sddm.reboot()
                    }
                }

                Rectangle {
                    width: 78; height: 28; radius: 6
                    visible: sddm.canPowerOff
                    color: offArea.containsMouse ? c_hover : "transparent"
                    border.color: c_border; border.width: 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors.centerIn: parent
                        text: "%%SDDM_SHUTDOWN%%"
                        color: c_red
                        font { pixelSize: 11; family: c_font }
                    }
                    MouseArea {
                        id: offArea; anchors.fill: parent
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: sddm.powerOff()
                    }
                }

                Item { Layout.fillWidth: true }
            }
        }
    }

    // ── Lógica ────────────────────────────────────────────────────
    function doLogin() {
        sddm.login(userField.text, passField.text, sessionCombo.currentIndex)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            loginFailed = true
            passField.text = ""
            passField.forceActiveFocus()
            failTimer.restart()
        }
        function onLoginSucceeded() {
            loginFailed = false
        }
    }

    Timer {
        id: failTimer
        interval: 4000
        onTriggered: loginFailed = false
    }

    Component.onCompleted: {
        if (userField.text.length > 0)
            passField.forceActiveFocus()
        else
            userField.forceActiveFocus()
    }
}
