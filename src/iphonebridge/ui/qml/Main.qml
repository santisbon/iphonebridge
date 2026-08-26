import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win

    // True while a new conversation is being addressed but not yet sent.
    property bool composing: false

    // A recipient box that suggests contacts as you type. Used by the
    // new-conversation form and by the dialer, which want exactly the
    // same behaviour and drifted apart when they were separate widgets.
    component RecipientField: Item {
        id: rf
        property alias text: field.text
        property string placeholder: ""
        // Two different things, and conflating them dialled a contact
        // the moment you picked them out of the list. `submitted` means
        // "go" — Enter in the field. `picked` means a name was chosen and
        // the field is now filled; the GTK version only moved focus.
        signal submitted()
        signal picked()

        implicitHeight: field.implicitHeight
        implicitWidth: field.implicitWidth

        TextField {
            id: field
            anchors.fill: parent
            placeholderText: rf.placeholder
            // onTextEdited, never onTextChanged: picking a suggestion
            // sets the text, and reacting to that would reopen the popup
            // over the choice just made. The GTK version needed an
            // explicit guard flag for the same reason.
            onTextEdited: {
                popup.rows = bridge.suggest(text)
                if (popup.rows.length > 0) popup.open(); else popup.close()
            }
            onAccepted: { popup.close(); rf.submitted() }
            Keys.onEscapePressed: popup.close()
        }

        Popup {
            id: popup
            property var rows: []
            y: field.height
            width: field.width
            padding: 1
            // Never takes focus: the field has to keep it so typing
            // continues to narrow the list.
            closePolicy: Popup.CloseOnPressOutside | Popup.CloseOnEscape
            implicitHeight: Math.min(contentItem.contentHeight + 2, 220)

            contentItem: ListView {
                clip: true
                model: popup.rows
                implicitHeight: contentHeight
                delegate: ItemDelegate {
                    width: ListView.view.width
                    onClicked: {
                        field.text = modelData.name
                        popup.close()
                        field.forceActiveFocus()
                        rf.picked()
                    }
                    contentItem: RowLayout {
                        spacing: 12
                        Label {
                            text: modelData.name
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: modelData.phone
                            opacity: 0.6
                            font.pointSize: 8
                        }
                    }
                }
            }
        }
    }
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

    // Transient feedback, the way the GTK window's toast overlay worked.
    // Anything that can fail says so here rather than only in a log.
    Rectangle {
        id: toast
        objectName: "toast"
        z: 100
        visible: opacity > 0
        opacity: 0
        radius: 8
        color: "#323232"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: Math.min(toastText.implicitWidth + 32, parent.width - 48)
        height: toastText.implicitHeight + 20
        Text {
            id: toastText
            anchors.centerIn: parent
            width: parent.width - 32
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            color: "white"
        }
        Behavior on opacity { NumberAnimation { duration: 150 } }
        Timer { id: toastHide; interval: 4000; onTriggered: toast.opacity = 0 }
        function show(text) {
            toastText.text = text
            opacity = 0.95
            toastHide.restart()
        }
    }

    Connections {
        target: bridge
        function onToast(text) { toast.show(text) }
        function onCallArrived() {
            tabs.currentIndex = 2      // Calls
            win.show()
            win.raise()
            win.requestActivate()
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

            // Compose mode: a recipient still being chosen, so the thread
            // header and the conversation give way to a "To:" row.
            Connections {
                target: bridge
                function onChanged() {
                    if (composing && bridge.threadName.length > 0
                        && bridge.composeError.length === 0)
                        composing = false
                }
            }

            ColumnLayout {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 240
                spacing: 0

                // Over the conversation list, where a new conversation is
                // plainly what it starts. In the GTK version this sat in
                // the window's header bar, next to the close button, and
                // read as a fourth window control.
                Button {
                    objectName: "newConversation"
                    Layout.fillWidth: true
                    Layout.margins: 6
                    text: "New Conversation"
                    onClicked: {
                        bridge.clearCompose()
                        composing = true
                        toField.text = ""
                        toField.forceActiveFocus()
                    }
                }

            ListView {
                id: threadList
                objectName: "threadList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: threads
                // Bound, never assigned: writing to currentIndex
                // from the delegate would break this binding and
                // freeze the highlight on a stale row.
                currentIndex: bridge.currentIndex
                delegate: ItemDelegate {
                    id: threadRow
                    width: threadList.width
                    highlighted: ListView.isCurrentItem
                    onClicked: bridge.openThread(model.key)
                    // Right-click or long-press, as in the GTK version.
                    // Deleting is local only: iOS ignores MAP deletes, so
                    // the menu and the toast both say "this computer".
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onSingleTapped: threadMenu.popup()
                    }
                    TapHandler {
                        acceptedButtons: Qt.LeftButton
                        onLongPressed: threadMenu.popup()
                    }
                    Menu {
                        id: threadMenu
                        MenuItem {
                            text: "Delete conversation"
                            onTriggered: bridge.deleteThread(model.key)
                        }
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
            }

            ColumnLayout {
                SplitView.fillWidth: true
                spacing: 0

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    spacing: 2
                    visible: bridge.threadName.length > 0 && !composing
                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: bridge.threadName
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    // The Bluetooth link, stated where it matters — in the
                    // conversation you are about to reply in.
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 5
                        Rectangle {
                            width: 8; height: 8; radius: 4
                            color: bridge.linkOk ? "#34C759" : "#FF9500"
                        }
                        Label {
                            text: bridge.linkText
                            font.pointSize: 8
                            opacity: 0.7
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    visible: composing
                    Label { text: "To:" }
                    RecipientField {
                        id: toField
                        objectName: "toField"
                        Layout.fillWidth: true
                        placeholder: "Contact name or number"
                        onSubmitted: composer.forceActiveFocus()
                        onPicked: composer.forceActiveFocus()
                    }
                    Button {
                        text: "Cancel"
                        onClicked: { composing = false; bridge.clearCompose() }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    text: bridge.composeError
                    visible: composing && text.length > 0
                    color: "#C0392B"
                    wrapMode: Text.Wrap
                }

                Label {
                    objectName: "noConversation"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.Wrap
                    opacity: 0.6
                    visible: !composing && bridge.threadName.length === 0
                    text: "No conversation selected\n\n"
                          + "Pick a thread on the left, or start a new one."
                }

                ListView {
                    id: messageList
                    objectName: "messageList"
                    visible: composing || bridge.threadName.length > 0
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
                        id: msgRow
                        width: messageList.width
                        topPadding: model.newRun ? 8 : 2

                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onSingleTapped: if (model.msgKey) msgMenu.popup()
                        }
                        TapHandler {
                            acceptedButtons: Qt.LeftButton
                            onLongPressed: if (model.msgKey) msgMenu.popup()
                        }
                        Menu {
                            id: msgMenu
                            MenuItem {
                                text: "Delete message"
                                onTriggered: bridge.deleteMessage(model.msgKey)
                            }
                        }

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
                            TextEdit {
                                id: bubbleText
                                anchors.centerIn: parent
                                width: parent.width - 26
                                wrapMode: Text.Wrap
                                text: model.body
                                color: model.outgoing ? "white" : "black"
                                // Selectable but not editable: copying a
                                // verification code out of a message was
                                // possible in the GTK version and is worth
                                // keeping.
                                readOnly: true
                                selectByMouse: true
                                selectionColor: model.outgoing ? "white"
                                                               : "#007AFF"
                                selectedTextColor: model.outgoing ? "#007AFF"
                                                                  : "white"
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
                        enabled: composing || bridge.threadName.length > 0
                        onAccepted: sendButton.send()
                    }
                    Button {
                        id: sendButton
                        text: "Send"
                        enabled: composer.enabled && composer.text.length > 0
                                 && (!composing || toField.text.length > 0)
                        function send() {
                            if (!enabled) return
                            if (composing) {
                                // Stays in compose until the daemon
                                // confirms; the thread it lands in is
                                // opened then, which is also what clears
                                // this form.
                                bridge.sendTo(toField.text, composer.text)
                            } else {
                                bridge.send(composer.text)
                            }
                            composer.text = ""
                        }
                        onClicked: send()
                    }
                }
            }
        }

        // ---- the other three, plain for now -------------------------
        Item {
        Label {
            objectName: "noNotifications"
            anchors.fill: parent
            anchors.margins: 24
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
            opacity: 0.6
            visible: notifications.count === 0
            text: "No notifications yet\n\n"
                  + "Per-app notifications from your iPhone — Slack, Mail, "
                  + "WhatsApp and the rest — show up here as they arrive."
        }
        ListView {
            anchors.fill: parent
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
        }

        ColumnLayout {
            spacing: 8
            Label {
                Layout.margins: 12
                Layout.bottomMargin: 0
                text: "Call audio routes through this computer's mic and speakers."
                opacity: 0.7
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.margins: 12
                Layout.topMargin: 0
                RecipientField {
                    id: dialEntry
                    objectName: "dialEntry"
                    Layout.fillWidth: true
                    placeholder: "Contact name or number e.g. 1 (800) MYAPPLE"
                    onSubmitted: bridge.dial(text)
                }
                Button { text: "Call"; onClicked: bridge.dial(dialEntry.text) }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 12
                Layout.rightMargin: 12
                Label {
                    text: "Active calls"
                    font.bold: true
                    Layout.fillWidth: true
                }
                // Per-call Hang up buttons only exist while a call does,
                // which left no sign the app could end one at all. This
                // stays visible and goes live when there is something to
                // hang up — the daemon has had HangupAll all along.
                Button {
                    objectName: "hangUpAll"
                    text: "Hang up all"
                    enabled: calls.count > 0
                    onClicked: bridge.hangupAll()
                }
            }
            Label {
                Layout.leftMargin: 12
                text: bridge.callSummary
                opacity: 0.6
                visible: text.length > 0
            }
            ListView {
                objectName: "callList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 12
                Layout.topMargin: 0
                clip: true
                spacing: 4
                model: calls
                delegate: Rectangle {
                    width: ListView.view.width
                    height: 52
                    radius: 8
                    color: "transparent"
                    border.width: 1
                    border.color: "#D0D0D0"
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 10
                        ColumnLayout {
                            spacing: 0
                            Layout.fillWidth: true
                            Label { text: model.peer; font.bold: true
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true }
                            Label { text: model.detail; opacity: 0.6
                                    font.pointSize: 8 }
                        }
                        Button {
                            objectName: "answerCall"
                            text: "Answer"
                            visible: model.canAnswer
                            onClicked: bridge.answer(model.path)
                        }
                        Button {
                            objectName: "hangUpCall"
                            text: "Hang up"
                            onClicked: bridge.hangup(model.path)
                        }
                    }
                }
            }
        }

        ColumnLayout {
            spacing: 6
            ListView {
                objectName: "statusList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 12
                clip: true
                spacing: 6
                model: bridge.statusRows
                header: Label {
                    width: ListView.view ? ListView.view.width : 0
                    bottomPadding: 8
                    wrapMode: Text.Wrap
                    opacity: 0.7
                    text: "On the iPhone: Settings → Bluetooth → tap ⓘ next "
                          + "to this computer, then enable each toggle."
                }
                delegate: RowLayout {
                    width: ListView.view ? ListView.view.width : 0
                    spacing: 8
                    // The three states the GTK page drew as tinted icons.
                    Rectangle {
                        width: 10; height: 10; radius: 5
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: 4
                        color: modelData.state === "ok" ? "#34C759"
                             : modelData.state === "warn" ? "#FF3B30"
                             : "#8E8E93"
                    }
                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true
                        Label { text: modelData.label; font.bold: true }
                        Label {
                            text: modelData.detail
                            opacity: 0.7
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
            Button {
                Layout.leftMargin: 12
                Layout.bottomMargin: 12
                text: "Recheck"
                onClicked: bridge.recheck()
            }
        }
    }
}
