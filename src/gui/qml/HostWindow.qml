import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 520
    height: Math.min(760, Math.max(320, 176 + processList.contentHeight))
    minimumWidth: 420
    minimumHeight: 280
    visible: false
    title: hostUi.title
    color: hostUi.darkTheme ? "#202124" : "#f5f6f8"

    property color card: hostUi.darkTheme ? "#292b2f" : "#ffffff"
    property color border: hostUi.darkTheme ? "#3c4047" : "#d8dce3"
    property color textColor: hostUi.darkTheme ? "#f2f3f5" : "#202124"
    property color mutedColor: hostUi.darkTheme ? "#aeb4bf" : "#667085"
    property color accent: hostUi.darkTheme ? "#6ea8fe" : "#2563eb"

    onClosing: function(close) {
        close.accepted = false
        root.visible = false
    }

    component SurfaceButton: Button {
        id: control
        implicitHeight: 34
        leftPadding: 13
        rightPadding: 13
        contentItem: Text {
            text: control.text
            color: root.textColor
            font.pixelSize: 13
            font.weight: Font.Medium
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 7
            color: control.down ? Qt.darker(root.card, 1.12) : control.hovered ? Qt.lighter(root.card, 1.08) : root.card
            border.color: control.hovered ? root.accent : root.border
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "숙제 관리자"
                color: root.textColor
                font.pixelSize: 20
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            SurfaceButton { text: "대시보드"; onClicked: hostUi.openDashboard() }
            SurfaceButton { text: "설정"; onClicked: hostUi.openSettings() }
            SurfaceButton { text: "+ 게임"; onClicked: hostUi.addProcess() }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: root.card
            border.color: root.border

            ListView {
                id: processList
                anchors.fill: parent
                anchors.margins: 6
                spacing: 4
                clip: true
                model: hostUi.processes

                delegate: Rectangle {
                    required property var modelData
                    width: processList.width
                    height: 72
                    radius: 8
                    color: rowMouse.containsMouse ? (hostUi.darkTheme ? "#32353a" : "#f3f6fb") : "transparent"

                    MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 10
                        spacing: 12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 5
                            Text {
                                text: modelData.name
                                color: root.textColor
                                font.pixelSize: 14
                                font.weight: Font.Medium
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                ProgressBar {
                                    from: 0; to: 100; value: modelData.progress
                                    Layout.fillWidth: true
                                    background: Rectangle { implicitHeight: 5; radius: 3; color: root.border }
                                    contentItem: Item {
                                        implicitHeight: 5
                                        Rectangle { width: parent.width * Math.max(0, Math.min(1, modelData.progress / 100)); height: 5; radius: 3; color: root.accent }
                                    }
                                }
                                Text { text: modelData.state; color: root.mutedColor; font.pixelSize: 12 }
                            }
                        }
                        SurfaceButton { text: "실행"; onClicked: hostUi.launchProcess(modelData.id) }
                    }
                }

                ScrollBar.vertical: ScrollBar {}
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text { text: "PySide6 · Qt Quick 후보"; color: root.mutedColor; font.pixelSize: 11; Layout.fillWidth: true }
            SurfaceButton { text: "원격 설정"; onClicked: hostUi.openRemoteSettings() }
        }
    }
}
