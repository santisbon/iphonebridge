import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 940; height: 720; visible: true
    title: "iphonebridge"

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            TabBar {
                id: tabs
                Layout.fillWidth: true
                TabButton { text: "Messages" }
                TabButton { text: "Notifications" }
                TabButton { text: "Calls" }
                TabButton { text: "Status" }
            }
        }
    }

    // Shown when the daemon is not on the bus at all.
    Rectangle {
        id: banner
        visible: !bridge.available
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: visible ? 34 : 0
        color: "#F6C344"
        Text {
            anchors.centerIn: parent
            text: "Daemon not reachable — systemctl --user start iphonebridge"
        }
    }

    StackLayout {
        anchors { top: banner.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }
        currentIndex: tabs.currentIndex

        // ---- Messages ----------------------------------------------
        SplitView {
            orientation: Qt.Horizontal

            ListView {
                id: threadList
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 240
                clip: true
                model: threads
                currentIndex: -1
                delegate: ItemDelegate {
                    width: threadList.width
                    highlighted: ListView.isCurrentItem
                    onClicked: {
                        threadList.currentIndex = index
                        bridge.openThread(model.key)
                    }
                    contentItem: ColumnLayout {
                        spacing: 1
                        RowLayout {
                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: "#007AFF"; visible: model.unread
                            }
                            Label {
                                text: model.name; font.bold: true
                                elide: Text.ElideRight; Layout.fillWidth: true
                            }
                            Label { text: model.stamp; opacity: 0.6; font.pointSize: 8 }
                        }
                        Label {
                            text: model.preview; opacity: 0.6
                            elide: Text.ElideRight; Layout.fillWidth: true
                        }
                    }
                }
            }

            ColumnLayout {
                SplitView.fillWidth: true
                spacing: 0

                Label {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    horizontalAlignment: Text.AlignHCenter
                    text: bridge.threadName
                    font.bold: true
                    visible: text.length > 0
                }

                ListView {
                    id: messageList
                    objectName: "messageList"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true
                    model: messages
                    spacing: 2

                    // The whole of the follow behaviour. callLater defers
                    // to after the delegate is laid out, which is what the
                    // GTK version could never reliably do.
                    onCountChanged: Qt.callLater(messageList.positionViewAtEnd)

                    delegate: Column {
                        width: messageList.width
                        topPadding: model.newRun ? 8 : 2

                        Label {
                            visible: model.dayText.length > 0
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            textFormat: Text.StyledText
                            text: model.dayText
                            opacity: 0.55
                            font.pointSize: 8
                            bottomPadding: 4
                        }
                        Rectangle {
                            anchors.right: model.outgoing ? parent.right : undefined
                            anchors.rightMargin: 12
                            x: model.outgoing ? 0 : 12
                            width: Math.min(bubbleText.implicitWidth + 26,
                                            messageList.width * 0.66)
                            height: bubbleText.implicitHeight + 14
                            radius: 18
                            color: model.outgoing ? "#007AFF" : "#E9E9EB"
                            Text {
                                id: bubbleText
                                anchors.centerIn: parent
                                width: parent.width - 26
                                wrapMode: Text.Wrap
                                text: model.body
                                color: model.outgoing ? "white" : "black"
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    TextField {
                        id: composer
                        Layout.fillWidth: true
                        placeholderText: "Message"
                        enabled: bridge.threadName.length > 0
                        onAccepted: sendButton.send()
                    }
                    Button {
                        id: sendButton
                        text: "Send"
                        enabled: composer.enabled && composer.text.length > 0
                        function send() {
                            if (!enabled) return
                            bridge.send(composer.text)
                            composer.text = ""
                        }
                        onClicked: send()
                    }
                }
            }
        }

        // ---- the other three, plain for now -------------------------
        ListView {
            clip: true
            model: notifications
            delegate: ItemDelegate {
                width: parent ? parent.width : 0
                contentItem: ColumnLayout {
                    RowLayout {
                        Label { text: model.app; font.bold: true; Layout.fillWidth: true }
                        Label { text: model.stamp; opacity: 0.6; font.pointSize: 8 }
                    }
                    Label { text: model.preview; opacity: 0.7
                            elide: Text.ElideRight; Layout.fillWidth: true }
                }
            }
        }

        ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.margins: 12
                TextField {
                    id: dialEntry
                    Layout.fillWidth: true
                    placeholderText: "Contact name or number e.g. 1 (800) MYAPPLE"
                    onAccepted: bridge.dial(text)
                }
                Button { text: "Call"; onClicked: bridge.dial(dialEntry.text) }
            }
            Label { Layout.margins: 12; text: bridge.callSummary }
            Item { Layout.fillHeight: true }
        }

        ColumnLayout {
            spacing: 6
            Label { Layout.margins: 12; text: bridge.statusText; textFormat: Text.StyledText }
            Button { Layout.leftMargin: 12; text: "Recheck"; onClicked: bridge.recheck() }
            Item { Layout.fillHeight: true }
        }
    }
}
