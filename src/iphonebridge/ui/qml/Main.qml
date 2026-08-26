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
                objectName: "tabs"
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
                objectName: "threadList"
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 240
                clip: true
                model: threads
                // Bound, never assigned: writing to currentIndex
                // from the delegate would break this binding and
                // freeze the highlight on a stale row.
                currentIndex: bridge.currentIndex
                delegate: ItemDelegate {
                    width: threadList.width
                    highlighted: ListView.isCurrentItem
                    onClicked: bridge.openThread(model.key)
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

                    // Following the end of a growing list takes two
                    // steps, not one. On countChanged the new delegate has
                    // not been laid out yet, so contentHeight is still an
                    // estimate built from one-line rows: positionViewAtEnd
                    // scrolls to that estimate and stops, leaving a tall
                    // wrapped message mostly below the edge. contentHeight
                    // changes again once the delegate is measured, and
                    // that is when the position has to be re-asserted.
                    property bool follow: true

                    // Written out rather than positionViewAtEnd(), which
                    // places the last row against the viewport as if the
                    // origin were zero. For a list of variable-height rows
                    // it is not: originY shifts as rows above the viewport
                    // get measured, and the view was then left short by
                    // exactly that shift. This is stated in the same terms
                    // the checks use, and re-running it is harmless.
                    function toEnd() {
                        var end = originY + contentHeight - height
                        contentY = end > originY ? end : originY
                    }

                    // Scrolling to the end moves the end: the rows that
                    // come into view get measured, which corrects
                    // contentHeight and originY again. One deferred call
                    // is not enough — on countChanged the new delegate is
                    // not laid out yet, so the end is still estimated from
                    // one-line rows, and stopping there is what left a
                    // tall wrapped message below the bottom edge. So
                    // re-assert a frame later, which is idempotent and
                    // settles as soon as nothing is moving.
                    Timer {
                        id: settle
                        interval: 16
                        onTriggered: if (messageList.follow) messageList.toEnd()
                    }

                    onCountChanged: { follow = true; toEnd(); settle.restart() }
                    onContentHeightChanged: if (follow) settle.restart()
                    onOriginYChanged: if (follow) settle.restart()
                    // Scrolling away stops the view yanking itself back
                    // while you read; the next message resumes following.
                    onMovementEnded: follow = atYEnd

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
