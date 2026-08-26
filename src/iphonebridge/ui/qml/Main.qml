import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 940; height: 720; visible: true
    title: "iphonebridge"
    color: theme.canvas

    // True while a new conversation is being addressed but not yet sent.
    property bool composing: false

    Theme { id: theme }

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

        implicitHeight: 30
        implicitWidth: field.implicitWidth

        TextField {
            id: field
            anchors.fill: parent
            placeholderText: rf.placeholder
            color: theme.label
            placeholderTextColor: theme.label2
            font.family: theme.ui
            font.pixelSize: theme.bodySize
            leftPadding: 12
            rightPadding: 12
            background: Rectangle {
                radius: theme.pillRadius
                color: theme.fill
                border.width: field.activeFocus ? 2 : 0
                border.color: theme.accent
            }
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
            y: field.height + 4
            width: field.width
            padding: 4
            closePolicy: Popup.CloseOnPressOutside | Popup.CloseOnEscape
            implicitHeight: Math.min(contentItem.contentHeight + 8, 240)
            background: Rectangle {
                radius: 10
                color: theme.canvas
                border.width: 1
                border.color: theme.separator
            }

            contentItem: ListView {
                clip: true
                model: popup.rows
                implicitHeight: contentHeight
                delegate: ItemDelegate {
                    id: sug
                    width: ListView.view.width
                    height: 30
                    onClicked: {
                        field.text = modelData.name
                        popup.close()
                        field.forceActiveFocus()
                        rf.picked()
                    }
                    background: Rectangle {
                        radius: 6
                        color: sug.hovered ? theme.fill : "transparent"
                    }
                    contentItem: RowLayout {
                        spacing: 12
                        Label {
                            text: modelData.name
                            color: theme.label
                            font.family: theme.ui
                            font.pixelSize: theme.bodySize
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: modelData.phone
                            color: theme.label2
                            font.family: theme.ui
                            font.pixelSize: theme.captionSize
                        }
                    }
                }
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
        radius: 10
        color: theme.dark ? "#3A3A3C" : "#323232"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 28
        width: Math.min(toastText.implicitWidth + 32, parent.width - 48)
        height: toastText.implicitHeight + 20
        Text {
            id: toastText
            anchors.centerIn: parent
            width: parent.width - 32
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            color: "white"
            font.family: theme.ui
            font.pixelSize: theme.bodySize
        }
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Timer { id: toastHide; interval: 4000; onTriggered: toast.opacity = 0 }
        function show(text) {
            toastText.text = text
            opacity = 0.96
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

    // A segmented control, centred — what Apple puts in a toolbar when a
    // window has a handful of peer sections.
    header: Rectangle {
        implicitHeight: 48
        color: theme.sidebar
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: theme.separator
        }
        TabBar {
            id: tabs
            objectName: "tabs"
            anchors.centerIn: parent
            implicitWidth: 420
            spacing: 2
            background: Rectangle {
                radius: 8
                color: theme.fill
            }
            Repeater {
                model: ["Messages", "Notifications", "Calls", "Setup"]
                TabButton {
                    id: tabBtn
                    text: modelData
                    height: 28
                    background: Rectangle {
                        radius: 7
                        color: tabBtn.checked ? theme.canvas : "transparent"
                        border.width: tabBtn.checked ? 1 : 0
                        border.color: theme.separator
                    }
                    contentItem: Text {
                        text: tabBtn.text
                        color: theme.label
                        font.family: theme.ui
                        font.pixelSize: theme.rowSize
                        font.weight: tabBtn.checked ? Font.DemiBold : Font.Normal
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }

    // Shown when the daemon is not on the bus at all.
    Rectangle {
        id: banner
        visible: !bridge.available
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: visible ? 30 : 0
        color: theme.down
        Text {
            anchors.centerIn: parent
            text: "Daemon not reachable — systemctl --user start iphonebridge"
            color: "#000000"
            font.family: theme.ui
            font.pixelSize: theme.captionSize
        }
    }

    StackLayout {
        anchors { top: banner.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }
        currentIndex: tabs.currentIndex

        // ---- Messages ----------------------------------------------
        SplitView {
            orientation: Qt.Horizontal
            handle: Rectangle { implicitWidth: 1; color: theme.separator }

            Connections {
                target: bridge
                // Only once the daemon has confirmed the send and the new
                // conversation is already open. Inferring the moment from
                // `changed` plus a non-empty thread name was wrong: both
                // were already true of the conversation you were last in,
                // so it flashed up for a frame before the new one replaced
                // it.
                function onComposeFinished() { composing = false }
            }

            Rectangle {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 240
                color: theme.sidebar

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Top of the sidebar, aligned right, icon only —
                    // where Messages puts it. The name it lost lives in
                    // the tooltip and in Accessible.name, so hovering or
                    // a screen reader still says what it does.
                    Item {
                        Layout.fillWidth: true
                        implicitHeight: 42

                        Button {
                            id: newBtn
                            objectName: "newConversation"
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: 30
                            implicitHeight: 30
                            Accessible.name: "New conversation"
                            ToolTip.visible: hovered
                            ToolTip.delay: 500
                            ToolTip.text: "New conversation"
                            onClicked: {
                                bridge.clearCompose()
                                composing = true
                                toField.text = ""
                                toField.forceActiveFocus()
                            }
                            background: Rectangle {
                                radius: 7
                                color: newBtn.down ? theme.selected
                                     : newBtn.hovered ? theme.fill
                                     : "transparent"
                            }
                            contentItem: Item {
                                ComposeMark {
                                    anchors.centerIn: parent
                                    color: theme.accent
                                }
                            }
                        }

                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width; height: 1
                            color: theme.separator
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
                        // freeze the highlight on a stale row. Composing
                        // clears it — you are not in a conversation, and a
                        // highlighted one says you are.
                        currentIndex: composing ? -1 : bridge.currentIndex
                        delegate: ItemDelegate {
                            id: threadRow
                            width: threadList.width
                            height: 62
                            onClicked: bridge.openThread(model.key)
                            // Right-click or long-press, as in the GTK
                            // version. Deleting is local only: iOS ignores
                            // MAP deletes, so the menu and the toast both
                            // say "this computer".
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
                            background: Rectangle {
                                color: threadRow.ListView.isCurrentItem
                                       ? theme.accent
                                       : threadRow.hovered ? theme.fill
                                                           : "transparent"
                                radius: threadRow.ListView.isCurrentItem ? 8 : 0
                                anchors.fill: parent
                                anchors.margins: threadRow.ListView.isCurrentItem ? 6 : 0
                                // Inset hairline, stopping short of the
                                // left edge the way a grouped iOS list does.
                                Rectangle {
                                    visible: !threadRow.ListView.isCurrentItem
                                    anchors.bottom: parent.bottom
                                    anchors.right: parent.right
                                    x: theme.gutter + 12
                                    width: parent.width - x
                                    height: 1
                                    color: theme.separator
                                }
                            }
                            contentItem: Item {
                                anchors.fill: parent
                                Rectangle {
                                    id: unreadDot
                                    width: 7; height: 7; radius: 3.5
                                    x: 5
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: threadRow.ListView.isCurrentItem
                                           ? "white" : theme.accent
                                    visible: model.unread
                                }
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: theme.gutter + 4
                                    anchors.rightMargin: theme.gutter
                                    anchors.topMargin: 10
                                    anchors.bottomMargin: 10
                                    spacing: 2
                                    RowLayout {
                                        spacing: 8
                                        Label {
                                            text: model.name
                                            color: threadRow.ListView.isCurrentItem
                                                   ? "white" : theme.label
                                            font.family: theme.ui
                                            font.pixelSize: theme.titleSize
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Label {
                                            text: model.stamp
                                            color: threadRow.ListView.isCurrentItem
                                                   ? Qt.rgba(1, 1, 1, 0.75)
                                                   : theme.label2
                                            font.family: theme.ui
                                            font.pixelSize: theme.captionSize
                                        }
                                    }
                                    Label {
                                        text: model.preview
                                        color: threadRow.ListView.isCurrentItem
                                               ? Qt.rgba(1, 1, 1, 0.85)
                                               : theme.label2
                                        font.family: theme.ui
                                        font.pixelSize: theme.bodySize
                                        elide: Text.ElideRight
                                        maximumLineCount: 1
                                        Layout.fillWidth: true
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                SplitView.fillWidth: true
                color: theme.canvas

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Conversation header. The ribbon under the name is the
                    // one thing this app has that Messages does not: the
                    // link is physical here, and it can go.
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        Layout.bottomMargin: 10
                        spacing: 3
                        visible: bridge.threadName.length > 0 && !composing
                        Label {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: bridge.threadName
                            color: theme.label
                            font.family: theme.ui
                            font.pixelSize: theme.titleSize
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter
                            implicitWidth: ribbon.implicitWidth + 20
                            implicitHeight: 19
                            radius: 9.5
                            color: theme.fill
                            RowLayout {
                                id: ribbon
                                anchors.centerIn: parent
                                spacing: 5
                                Rectangle {
                                    width: 6; height: 6; radius: 3
                                    color: bridge.linkOk ? theme.up : theme.down
                                    Behavior on color { ColorAnimation { duration: 200 } }
                                }
                                Label {
                                    text: bridge.linkText
                                    color: theme.label2
                                    font.family: theme.ui
                                    font.pixelSize: theme.captionSize
                                    font.letterSpacing: 0.3
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 12
                        visible: composing
                        spacing: 8
                        Label {
                            text: "To:"
                            color: theme.label2
                            font.family: theme.ui
                            font.pixelSize: theme.bodySize
                        }
                        RecipientField {
                            id: toField
                            objectName: "toField"
                            Layout.fillWidth: true
                            placeholder: "Contact name or number"
                            onSubmitted: composer.forceActiveFocus()
                            onPicked: composer.forceActiveFocus()
                        }
                        Button {
                            id: cancelBtn
                            text: "Cancel"
                            flat: true
                            onClicked: { composing = false; bridge.clearCompose() }
                            contentItem: Text {
                                text: cancelBtn.text
                                color: theme.accent
                                font.family: theme.ui
                                font.pixelSize: theme.bodySize
                                verticalAlignment: Text.AlignVCenter
                            }
                            background: Item {}
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: 12
                        Layout.rightMargin: 12
                        text: bridge.composeError
                        visible: composing && text.length > 0
                        color: theme.destructive
                        font.family: theme.ui
                        font.pixelSize: theme.bodySize
                        wrapMode: Text.Wrap
                    }

                    Label {
                        objectName: "noConversation"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.margins: 40
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.Wrap
                        color: theme.label2
                        font.family: theme.ui
                        font.pixelSize: theme.bodySize
                        visible: !composing && bridge.threadName.length === 0
                        text: "No conversation selected\n\n"
                              + "Pick a thread on the left, or start a new one."
                    }

                    Label {
                        objectName: "newMessageHint"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.margins: 40
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.Wrap
                        color: theme.label2
                        font.family: theme.ui
                        font.pixelSize: theme.bodySize
                        visible: composing
                        text: "New message\n\n"
                              + "Enter a name or number above, then write "
                              + "your message below."
                    }

                    ListView {
                        id: messageList
                        objectName: "messageList"
                        // Not while composing. A new message has no thread
                        // yet, and leaving the last one on screen under the
                        // To field reads as though you are about to reply
                        // into it.
                        visible: !composing && bridge.threadName.length > 0
                        Layout.fillWidth: true; Layout.fillHeight: true
                        clip: true
                        model: messages
                        spacing: 2

                        // Following the end of a growing list takes two
                        // steps, not one. On countChanged the new delegate
                        // has not been laid out yet, so contentHeight is
                        // still an estimate built from one-line rows, and
                        // stopping there is what left a tall wrapped
                        // message below the bottom edge.
                        property bool follow: true

                        // Written out rather than positionViewAtEnd(),
                        // which places the last row as if the origin were
                        // zero. For variable-height rows it is not: originY
                        // shifts as rows above the viewport get measured,
                        // and the view was left short by exactly that.
                        // A conversation shorter than the pane belongs
                        // against the composer, not pinned under the
                        // header with a void beneath it. The padding that
                        // does that is *assigned*, never bound: topMargin
                        // changes the flickable's extents, which changes
                        // which delegates are realised, which re-estimates
                        // contentHeight — bound, that is a loop, and Qt
                        // says so. Assigning from the settle timer lets it
                        // converge the same way the scrolling does.
                        function reflow() {
                            var want = Math.max(0, height - contentHeight)
                            if (Math.abs(want - topMargin) > 0.5)
                                topMargin = want
                            toEnd()
                        }

                        function toEnd() {
                            // The lowest contentY can go is originY minus
                            // the top margin: the padding showing, and the
                            // conversation resting on the composer.
                            var floor = originY - topMargin
                            var end = originY + contentHeight - height
                            contentY = end > floor ? end : floor
                        }

                        Timer {
                            id: settle
                            interval: 16
                            onTriggered: if (messageList.follow) messageList.reflow()
                        }

                        onCountChanged: { follow = true; reflow(); settle.restart() }
                        onContentHeightChanged: if (follow) settle.restart()
                        onOriginYChanged: if (follow) settle.restart()
                        onHeightChanged: if (follow) settle.restart()
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
                                color: theme.label2
                                font.family: theme.ui
                                font.pixelSize: theme.captionSize
                                font.letterSpacing: 0.3
                                topPadding: 6
                                bottomPadding: 6
                            }
                            Rectangle {
                                anchors.right: model.outgoing ? parent.right : undefined
                                anchors.rightMargin: theme.gutter
                                x: model.outgoing ? 0 : theme.gutter
                                width: Math.min(bubbleText.implicitWidth + 24,
                                                messageList.width * theme.bubbleMax)
                                height: bubbleText.implicitHeight + 14
                                radius: theme.bubbleRadius
                                color: model.outgoing ? theme.accent : theme.bubbleIn
                                TextEdit {
                                    id: bubbleText
                                    anchors.centerIn: parent
                                    width: parent.width - 24
                                    wrapMode: Text.Wrap
                                    text: model.body
                                    color: model.outgoing ? "white" : theme.bubbleInText
                                    font.family: theme.ui
                                    font.pixelSize: theme.bodySize
                                    // Selectable but not editable: copying
                                    // a verification code out of a message
                                    // was possible before and is worth
                                    // keeping.
                                    readOnly: true
                                    selectByMouse: true
                                    selectionColor: model.outgoing
                                                    ? Qt.rgba(1, 1, 1, 0.35)
                                                    : theme.accent
                                    selectedTextColor: model.outgoing
                                                       ? "white" : "white"
                                }
                            }
                        }
                    }

                    // Composer. The send button only exists once there is
                    // something to send, which is how Messages behaves and
                    // is the reason the field can stay this quiet.
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: 12
                        spacing: 8
                        TextField {
                            id: composer
                            Layout.fillWidth: true
                            implicitHeight: 32
                            placeholderText: bridge.linkOk ? "Message"
                                                           : "Waiting for the iPhone"
                            enabled: (composing || bridge.threadName.length > 0)
                                     && bridge.linkOk
                            color: theme.label
                            placeholderTextColor: theme.label2
                            font.family: theme.ui
                            font.pixelSize: theme.bodySize
                            leftPadding: 14
                            rightPadding: 14
                            background: Rectangle {
                                radius: theme.pillRadius
                                color: composer.enabled ? "transparent" : theme.fill
                                border.width: 1
                                border.color: composer.activeFocus ? theme.accent
                                                                   : theme.separator
                            }
                            onAccepted: sendButton.send()
                        }
                        Button {
                            id: sendButton
                            implicitWidth: 32; implicitHeight: 32
                            enabled: composer.enabled && composer.text.length > 0
                                     && (!composing || toField.text.length > 0)
                            opacity: enabled ? 1 : 0
                            scale: enabled ? 1 : 0.6
                            visible: opacity > 0
                            Behavior on opacity { NumberAnimation { duration: 120 } }
                            Behavior on scale {
                                NumberAnimation { duration: 140; easing.type: Easing.OutBack }
                            }
                            function send() {
                                if (!enabled) return
                                if (composing) {
                                    // Stays in compose until the daemon
                                    // confirms; the thread it lands in is
                                    // opened then, which clears this form.
                                    bridge.sendTo(toField.text, composer.text)
                                } else {
                                    bridge.send(composer.text)
                                }
                                composer.text = ""
                            }
                            onClicked: send()
                            background: Rectangle {
                                radius: width / 2
                                color: sendButton.down ? Qt.darker(theme.accent, 1.15)
                                                       : theme.accent
                            }
                            contentItem: Canvas {
                                onPaint: {
                                    var c = getContext("2d")
                                    c.reset()
                                    c.strokeStyle = "white"
                                    c.lineWidth = 2
                                    c.lineCap = "round"
                                    c.lineJoin = "round"
                                    var cx = width / 2, top = height / 2 - 5.5
                                    c.beginPath()
                                    c.moveTo(cx, height / 2 + 5.5)
                                    c.lineTo(cx, top)
                                    c.moveTo(cx - 4.5, top + 4.5)
                                    c.lineTo(cx, top)
                                    c.lineTo(cx + 4.5, top + 4.5)
                                    c.stroke()
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- Notifications ------------------------------------------
        Rectangle {
            color: theme.canvas
            Label {
                objectName: "noNotifications"
                anchors.fill: parent
                anchors.margins: 40
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
                color: theme.label2
                font.family: theme.ui
                font.pixelSize: theme.bodySize
                visible: notifications.count === 0
                text: "No notifications yet\n\n"
                      + "Per-app notifications from your iPhone — Slack, Mail, "
                      + "WhatsApp and the rest — show up here as they arrive."
            }
            ListView {
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                spacing: 8
                model: notifications
                delegate: Rectangle {
                    width: ListView.view.width
                    height: 54
                    radius: 12
                    color: theme.fill
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 2
                        RowLayout {
                            spacing: 8
                            Label {
                                text: model.app
                                color: theme.label
                                font.family: theme.ui
                                font.pixelSize: theme.rowSize
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                            Label {
                                text: model.stamp
                                color: theme.label2
                                font.family: theme.ui
                                font.pixelSize: theme.captionSize
                            }
                        }
                        Label {
                            text: model.preview
                            color: theme.label2
                            font.family: theme.ui
                            font.pixelSize: theme.bodySize
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        // ---- Calls ---------------------------------------------------
        Rectangle {
            color: theme.canvas
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Label {
                    text: "Call audio routes through this computer's mic and speakers."
                    color: theme.label2
                    font.family: theme.ui
                    font.pixelSize: theme.bodySize
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    RecipientField {
                        id: dialEntry
                        objectName: "dialEntry"
                        Layout.fillWidth: true
                        placeholder: "Contact name or number e.g. 1 (800) MYAPPLE"
                        onSubmitted: bridge.dial(text)
                    }
                    Button {
                        id: callBtn
                        implicitWidth: 76; implicitHeight: 30
                        onClicked: bridge.dial(dialEntry.text)
                        background: Rectangle {
                            radius: theme.pillRadius
                            color: callBtn.down ? Qt.darker(theme.up, 1.15) : theme.up
                        }
                        contentItem: Text {
                            text: "Call"
                            color: "white"
                            font.family: theme.ui
                            font.pixelSize: theme.rowSize
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    Label {
                        text: "Active calls"
                        color: theme.label2
                        font.family: theme.ui
                        font.pixelSize: theme.captionSize
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.6
                        Layout.fillWidth: true
                    }
                    // Per-call Hang up buttons only exist while a call
                    // does, which left no sign the app could end one.
                    Button {
                        id: hangAll
                        objectName: "hangUpAll"
                        implicitHeight: 26
                        enabled: calls.count > 0
                        onClicked: bridge.hangupAll()
                        background: Rectangle {
                            radius: 13
                            color: hangAll.down ? theme.fill : "transparent"
                            border.width: 1
                            border.color: hangAll.enabled ? theme.destructive
                                                          : theme.separator
                        }
                        contentItem: Text {
                            text: "Hang up all"
                            color: hangAll.enabled ? theme.destructive : theme.label2
                            font.family: theme.ui
                            font.pixelSize: theme.captionSize
                            leftPadding: 12; rightPadding: 12
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
                Label {
                    text: bridge.callSummary
                    color: theme.label2
                    font.family: theme.ui
                    font.pixelSize: theme.bodySize
                    visible: text.length > 0
                }
                ListView {
                    objectName: "callList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: calls
                    delegate: Rectangle {
                        width: ListView.view.width
                        height: 56
                        radius: 12
                        color: theme.fill
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 10
                            spacing: 10
                            ColumnLayout {
                                spacing: 1
                                Layout.fillWidth: true
                                Label {
                                    text: model.peer
                                    color: theme.label
                                    font.family: theme.ui
                                    font.pixelSize: theme.titleSize
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Label {
                                    text: model.detail
                                    color: theme.label2
                                    font.family: theme.ui
                                    font.pixelSize: theme.captionSize
                                }
                            }
                            // Named, not glyphed. A circle with an arrow
                            // in it is style at the cost of telling you
                            // which button ends the call.
                            Button {
                                id: answerBtn
                                objectName: "answerCall"
                                visible: model.canAnswer
                                implicitWidth: 74; implicitHeight: 30
                                onClicked: bridge.answer(model.path)
                                background: Rectangle {
                                    radius: height / 2
                                    color: answerBtn.down ? Qt.darker(theme.up, 1.15)
                                                          : theme.up
                                }
                                contentItem: Text {
                                    text: "Answer"
                                    color: "white"
                                    font.family: theme.ui
                                    font.pixelSize: theme.rowSize
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                            Button {
                                id: hangBtn
                                objectName: "hangUpCall"
                                implicitWidth: 74; implicitHeight: 30
                                onClicked: bridge.hangup(model.path)
                                background: Rectangle {
                                    radius: height / 2
                                    color: hangBtn.down
                                           ? Qt.darker(theme.destructive, 1.15)
                                           : theme.destructive
                                }
                                contentItem: Text {
                                    text: "Hang up"
                                    color: "white"
                                    font.family: theme.ui
                                    font.pixelSize: theme.rowSize
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- Setup ---------------------------------------------------
        Rectangle {
            color: theme.canvas
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10
                ListView {
                    objectName: "statusList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 10
                    model: bridge.statusRows
                    header: Label {
                        width: ListView.view ? ListView.view.width : 0
                        bottomPadding: 12
                        wrapMode: Text.Wrap
                        color: theme.label2
                        font.family: theme.ui
                        font.pixelSize: theme.bodySize
                        text: "On the iPhone: Settings → Bluetooth → tap ⓘ next "
                              + "to this computer, then enable each toggle."
                    }
                    delegate: RowLayout {
                        width: ListView.view ? ListView.view.width : 0
                        spacing: 10
                        Rectangle {
                            width: 9; height: 9; radius: 4.5
                            Layout.alignment: Qt.AlignTop
                            Layout.topMargin: 4
                            color: modelData.state === "ok" ? theme.up
                                 : modelData.state === "warn" ? theme.destructive
                                 : theme.label2
                        }
                        ColumnLayout {
                            spacing: 1
                            Layout.fillWidth: true
                            Label {
                                text: modelData.label
                                color: theme.label
                                font.family: theme.ui
                                font.pixelSize: theme.rowSize
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: modelData.detail
                                color: theme.label2
                                // The one place a monospaced face earns
                                // itself: this tab is a readout.
                                font.family: theme.mono
                                font.pixelSize: theme.captionSize
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
                Button {
                    id: recheckBtn
                    implicitHeight: 30
                    implicitWidth: 96
                    onClicked: bridge.recheck()
                    background: Rectangle {
                        radius: 8
                        color: recheckBtn.down ? theme.selected : theme.fill
                    }
                    contentItem: Text {
                        text: "Recheck"
                        color: theme.accent
                        font.family: theme.ui
                        font.pixelSize: theme.rowSize
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }
    }
}
