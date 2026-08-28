import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 940; height: 720; visible: true
    title: "iPhone Bridge"
    color: appTheme.canvas

    // True while a new conversation is being addressed but not yet sent.
    property bool composing: false

    // Named so it cannot be shadowed: inside a component that
    // has its own `theme` property, `theme: appTheme` binds the
    // property to itself and resolves to null.
    Theme { id: appTheme }

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

        implicitHeight: appTheme.fieldHeight
        implicitWidth: field.implicitWidth

        TextField {
            id: field
            anchors.fill: parent
            placeholderText: rf.placeholder
            color: appTheme.label
            placeholderTextColor: appTheme.label2
            font.family: appTheme.ui
            renderType: Text.CurveRendering
            font.pointSize: appTheme.bodySize
            leftPadding: 12
            rightPadding: 12
            background: Rectangle {
                radius: appTheme.pillRadius
                color: appTheme.fill
                border.width: field.activeFocus ? 2 : 0
                border.color: appTheme.accent
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
                color: appTheme.canvas
                border.width: 1
                border.color: appTheme.separator
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
                        color: sug.hovered ? appTheme.hover : "transparent"
                    }
                    contentItem: RowLayout {
                        spacing: 12
                        Label {
                            text: modelData.name
                            color: appTheme.label
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.bodySize
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Label {
                            text: modelData.phone
                            color: appTheme.label2
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.captionSize
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
        color: appTheme.dark ? "#3A3A3C" : "#323232"
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
            font.family: appTheme.ui
            renderType: Text.CurveRendering
            font.pointSize: appTheme.bodySize
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
        color: appTheme.sidebar
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: appTheme.separator
        }
        TabBar {
            id: tabs
            objectName: "tabs"
            anchors.centerIn: parent
            implicitWidth: Math.round(550 * appTheme.k)
            spacing: 2
            background: Rectangle {
                radius: 8
                color: appTheme.fill
            }
            Repeater {
                model: ["Messages", "Notifications", "Calls", "Music",
                        "Status"]
                TabButton {
                    id: tabBtn
                    text: modelData
                    height: Math.round(30 * appTheme.k)
                    background: Rectangle {
                        radius: 7
                        color: tabBtn.checked ? appTheme.canvas : "transparent"
                        border.width: tabBtn.checked ? 1 : 0
                        border.color: appTheme.separator
                    }
                    contentItem: Text {
                        text: tabBtn.text
                        color: appTheme.label
                        font.family: appTheme.ui
                        renderType: Text.CurveRendering
                        font.pointSize: appTheme.rowSize
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
        color: appTheme.down
        Text {
            anchors.centerIn: parent
            text: "Daemon not reachable — systemctl --user start iphonebridge"
            color: "#000000"
            font.family: appTheme.ui
            renderType: Text.CurveRendering
            font.pointSize: appTheme.captionSize
        }
    }

    StackLayout {
        anchors { top: banner.bottom; left: parent.left
                  right: parent.right; bottom: parent.bottom }
        currentIndex: tabs.currentIndex

        // ---- Messages ----------------------------------------------
        SplitView {
            orientation: Qt.Horizontal
            handle: Rectangle { implicitWidth: 1; color: appTheme.separator }

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
                color: appTheme.sidebar

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Top of the sidebar, aligned right, icon only —
                    // where Messages puts it. The name it lost lives in
                    // the tooltip and in Accessible.name, so hovering or
                    // a screen reader still says what it does.
                    Item {
                        Layout.fillWidth: true
                        implicitHeight: Math.round(38 * appTheme.k)

                        Button {
                            id: newBtn
                            objectName: "newConversation"
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: Math.round(30 * appTheme.k)
                            implicitHeight: Math.round(30 * appTheme.k)
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
                                color: newBtn.down ? appTheme.pressed
                                     : newBtn.hovered ? appTheme.hover
                                     : "transparent"
                            }
                            contentItem: Item {
                                ComposeMark {
                                    anchors.centerIn: parent
                                    color: appTheme.accent
                                    k: appTheme.k
                                    size: 22
                                }
                            }
                        }

                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width; height: 1
                            color: appTheme.separator
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
                            height: appTheme.rowHeight
                            onClicked: bridge.openThread(model.key)
                            // Right-click or long-press, as in the GTK
                            // version. Deleting is local only: iOS ignores
                            // MAP deletes, so the menu and the toast both
                            // say "this computer".
                            TapHandler {
                                id: threadRightTap
                                acceptedButtons: Qt.RightButton
                                onSingleTapped: threadMenu.popupAt(point.position)
                            }
                            TapHandler {
                                id: threadLongTap
                                acceptedButtons: Qt.LeftButton
                                onLongPressed: threadMenu.popupAt(point.position)
                            }
                            ActionMenu {
                                id: threadMenu
                                theme: appTheme
                                label: "Delete"
                                destructive: true
                                onActivated: bridge.deleteThread(model.key)
                            }
                            background: Rectangle {
                                color: threadRow.ListView.isCurrentItem
                                       ? appTheme.accent
                                       : threadRow.hovered ? appTheme.hover
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
                                    x: appTheme.gutter + 12
                                    width: parent.width - x
                                    height: 1
                                    color: appTheme.separator
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
                                           ? "white" : appTheme.accent
                                    visible: model.unread
                                }
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: appTheme.gutter + 4
                                    anchors.rightMargin: appTheme.gutter
                                    anchors.topMargin: 10
                                    anchors.bottomMargin: 10
                                    spacing: 2
                                    RowLayout {
                                        spacing: 8
                                        Label {
                                            text: model.name
                                            color: threadRow.ListView.isCurrentItem
                                                   ? "white" : appTheme.label
                                            font.family: appTheme.ui
                                            renderType: Text.CurveRendering
                                            font.pointSize: appTheme.titleSize
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Label {
                                            text: model.stamp
                                            color: threadRow.ListView.isCurrentItem
                                                   ? Qt.rgba(1, 1, 1, 0.75)
                                                   : appTheme.label2
                                            font.family: appTheme.ui
                                            renderType: Text.CurveRendering
                                            font.pointSize: appTheme.captionSize
                                        }
                                    }
                                    Label {
                                        text: model.preview
                                        color: threadRow.ListView.isCurrentItem
                                               ? Qt.rgba(1, 1, 1, 0.85)
                                               : appTheme.label2
                                        font.family: appTheme.ui
                                        renderType: Text.CurveRendering
                                        font.pointSize: appTheme.subSize
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
                color: appTheme.canvas

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
                            color: appTheme.label
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.titleSize
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter
                            implicitWidth: ribbon.implicitWidth + 20
                            implicitHeight: 19
                            radius: 9.5
                            color: appTheme.fill
                            RowLayout {
                                id: ribbon
                                anchors.centerIn: parent
                                spacing: 5
                                Rectangle {
                                    width: 6; height: 6; radius: 3
                                    color: bridge.linkOk ? appTheme.up : appTheme.down
                                    Behavior on color { ColorAnimation { duration: 200 } }
                                }
                                Label {
                                    text: bridge.linkText
                                    color: appTheme.label2
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
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
                            color: appTheme.label2
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.bodySize
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
                                color: appTheme.accent
                                font.family: appTheme.ui
                                renderType: Text.CurveRendering
                                font.pointSize: appTheme.bodySize
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
                        color: appTheme.destructive
                        font.family: appTheme.ui
                        renderType: Text.CurveRendering
                        font.pointSize: appTheme.bodySize
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
                        color: appTheme.label2
                        font.family: appTheme.ui
                        renderType: Text.CurveRendering
                        font.pointSize: appTheme.bodySize
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
                        color: appTheme.label2
                        font.family: appTheme.ui
                        renderType: Text.CurveRendering
                        font.pointSize: appTheme.bodySize
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
                        // Emoji inside a message are drawn larger than the
                        // words: at the reading size they are too small to
                        // make out. The model needs the number; only the
                        // view knows the type scale.
                        Component.onCompleted: messages.emojiPointSize =
                                               appTheme.bodySize * 1.4
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
                                id: msgRightTap
                                acceptedButtons: Qt.RightButton
                                onSingleTapped: if (model.msgKey)
                                                    msgMenu.popupAt(point.position)
                            }
                            TapHandler {
                                id: msgLongTap
                                acceptedButtons: Qt.LeftButton
                                onLongPressed: if (model.msgKey)
                                                   msgMenu.popupAt(point.position)
                            }
                            ActionMenu {
                                id: msgMenu
                                theme: appTheme
                                label: "Delete"
                                destructive: true
                                onActivated: bridge.deleteMessage(model.msgKey)
                            }

                            Row {
                                visible: model.dayName.length > 0
                                anchors.horizontalCenter: parent.horizontalCenter
                                spacing: Math.round(5 * appTheme.k)
                                topPadding: 6
                                bottomPadding: 6
                                Label {
                                    text: model.dayName
                                    color: appTheme.label2
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    text: model.dayTime
                                    color: appTheme.label2
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
                                }
                            }
                            Rectangle {
                                anchors.right: model.outgoing ? parent.right : undefined
                                anchors.rightMargin: appTheme.gutter
                                x: model.outgoing ? 0 : appTheme.gutter
                                // A message that is nothing but a couple of
                                // emoji is drawn large and bare, the way
                                // Messages does it: there the picture is
                                // the message, and a bubble around it is
                                // decoration on a decoration.
                                readonly property bool bare: model.emojiOnly
                                width: Math.min(bubbleText.implicitWidth + (bare ? 0 : 24),
                                                messageList.width * appTheme.bubbleMax)
                                height: bubbleText.implicitHeight + (bare ? 2 : 14)
                                radius: appTheme.bubbleRadius
                                color: bare ? "transparent"
                                     : model.outgoing ? appTheme.accent : appTheme.bubbleIn
                                TextEdit {
                                    id: bubbleText
                                    anchors.centerIn: parent
                                    width: parent.width - (parent.bare ? 0 : 24)
                                    wrapMode: Text.Wrap
                                    // Rich text only where it buys the
                                    // larger emoji. An emoji-only message
                                    // is already scaled whole, and a plain
                                    // message stays plain so it keeps the
                                    // clean curve-rendered text path.
                                    textFormat: parent.bare || !model.richBody
                                                ? Text.PlainText
                                                : Text.RichText
                                    text: parent.bare || !model.richBody
                                          ? model.body : model.bodyHtml
                                    color: parent.bare ? appTheme.label
                                         : model.outgoing ? "white"
                                                          : appTheme.bubbleInText
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: parent.bare ? appTheme.bodySize * 2.6
                                                                : appTheme.bodySize
                                    // Selectable but not editable: copying
                                    // a verification code out of a message
                                    // was possible before and is worth
                                    // keeping.
                                    readOnly: true
                                    selectByMouse: true
                                    selectionColor: model.outgoing
                                                    ? Qt.rgba(1, 1, 1, 0.35)
                                                    : appTheme.accent
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
                        Button {
                            id: emojiButton
                            objectName: "emojiButton"
                            implicitWidth: appTheme.fieldHeight
                            implicitHeight: appTheme.fieldHeight
                            enabled: composer.enabled
                            opacity: enabled ? 1 : 0.4
                            onClicked: emojiPicker.opened ? emojiPicker.close()
                                                          : emojiPicker.open()
                            background: Rectangle {
                                radius: width / 2
                                color: emojiButton.down ? appTheme.pressed
                                       : emojiButton.hovered ? appTheme.hover
                                                             : "transparent"
                            }
                            // A drawn smiley, not a colour emoji: chrome
                            // stays monochrome like every other control.
                            contentItem: Canvas {
                                onPaint: {
                                    var c = getContext("2d")
                                    c.reset()
                                    c.strokeStyle = appTheme.label2
                                    c.fillStyle = appTheme.label2
                                    c.lineWidth = 1.6
                                    c.lineCap = "round"
                                    var cx = width / 2, cy = height / 2
                                    var r = 8.5 * appTheme.k
                                    c.beginPath()
                                    c.arc(cx, cy, r, 0, 2 * Math.PI)
                                    c.stroke()
                                    c.beginPath()
                                    c.arc(cx, cy + r * 0.15, r * 0.55,
                                          0.15 * Math.PI, 0.85 * Math.PI)
                                    c.stroke()
                                    var er = Math.max(1.1, r * 0.14)
                                    c.beginPath()
                                    c.arc(cx - r * 0.38, cy - r * 0.3,
                                          er, 0, 2 * Math.PI)
                                    c.fill()
                                    c.beginPath()
                                    c.arc(cx + r * 0.38, cy - r * 0.3,
                                          er, 0, 2 * Math.PI)
                                    c.fill()
                                }
                            }
                            EmojiPicker {
                                id: emojiPicker
                                theme: appTheme
                                // Above the composer, left-aligned with
                                // the button that opens it.
                                x: 0
                                y: -height - Math.round(8 * appTheme.k)
                                onPicked: emoji => {
                                    composer.insert(
                                        composer.cursorPosition, emoji)
                                    bridge.noteEmojiUsed(emoji)
                                }
                                onClosed: composer.forceActiveFocus()
                            }
                        }
                        TextField {
                            id: composer
                            objectName: "composer"
                            Layout.fillWidth: true
                            implicitHeight: appTheme.fieldHeight
                            placeholderText: bridge.linkOk ? "Message"
                                                           : "Waiting for the iPhone"
                            enabled: (composing || bridge.threadName.length > 0)
                                     && bridge.linkOk
                            color: appTheme.label
                            placeholderTextColor: appTheme.label2
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.bodySize
                            leftPadding: 14
                            rightPadding: 14
                            background: Rectangle {
                                radius: appTheme.pillRadius
                                color: composer.enabled ? "transparent" : appTheme.fill
                                border.width: 1
                                border.color: composer.activeFocus ? appTheme.accent
                                                                   : appTheme.separator
                            }
                            onAccepted: sendButton.send()
                        }
                        Button {
                            id: sendButton
                            implicitWidth: appTheme.fieldHeight
                            implicitHeight: appTheme.fieldHeight
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
                                color: sendButton.down ? Qt.darker(appTheme.accent, 1.15)
                                                       : appTheme.accent
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
        // Notification Center's shape: a narrow column of light cards on
        // the grouped background, grouped under the app that sent them.
        Rectangle {
            color: appTheme.sidebar

            Label {
                objectName: "noNotifications"
                anchors.fill: parent
                anchors.margins: Math.round(40 * appTheme.k)
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
                color: appTheme.label2
                font.family: appTheme.ui
                renderType: Text.CurveRendering
                font.pointSize: appTheme.bodySize
                visible: notifications.count === 0
                text: "No notifications yet\n\n"
                      + "Per-app notifications from your iPhone — Slack, Mail, "
                      + "WhatsApp and the rest — show up here as they arrive."
            }

            ListView {
                // Explicit edges, not anchors.fill: fill would override
                // the width below and stretch the cards across the window.
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: appTheme.gutter
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width - 2 * appTheme.gutter,
                                Math.round(620 * appTheme.k))
                clip: true
                spacing: Math.round(6 * appTheme.k)
                model: notifications
                visible: notifications.count > 0
                ScrollBar.vertical: ScrollBar {}

                // Consecutive notifications from one app sit under its
                // name, the way Notification Center stacks them.
                section.property: "app"
                section.criteria: ViewSection.FullString
                section.delegate: Label {
                    width: ListView.view.width
                    leftPadding: appTheme.gutter
                    topPadding: Math.round(14 * appTheme.k)
                    bottomPadding: Math.round(5 * appTheme.k)
                    text: section.toUpperCase()
                    color: appTheme.label2
                    font.family: appTheme.ui
                    renderType: Text.CurveRendering
                    font.pointSize: appTheme.captionSize
                }

                delegate: Rectangle {
                    id: noteCard
                    width: ListView.view.width
                    implicitHeight: note.implicitHeight + Math.round(20 * appTheme.k)
                    radius: Math.round(10 * appTheme.k)
                    color: appTheme.canvas

                    // Dismissal, both ways: this ✕ (or right-click →
                    // Dismiss) removes the notification here and — when
                    // it is from the live BLE session — on the iPhone
                    // via ANCS's negative action. Hover-revealed, the
                    // way a macOS notification offers its close.
                    HoverHandler { id: noteHover }
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onSingleTapped: noteMenu.popup()
                    }
                    ActionMenu {
                        id: noteMenu
                        theme: appTheme
                        label: "Dismiss"
                        onActivated: bridge.dismissNotification(model.eid)
                    }
                    Rectangle {
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: Math.round(6 * appTheme.k)
                        width: Math.round(18 * appTheme.k)
                        height: width
                        radius: width / 2
                        z: 2
                        visible: noteHover.hovered || xArea.containsMouse
                        color: xArea.containsMouse ? appTheme.pressed
                                                   : appTheme.hover
                        Text {
                            anchors.centerIn: parent
                            text: "\u00d7"
                            color: appTheme.label2
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.rowSize
                        }
                        MouseArea {
                            id: xArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: bridge.dismissNotification(model.eid)
                        }
                    }

                    ColumnLayout {
                        id: note
                        x: appTheme.gutter
                        y: Math.round(10 * appTheme.k)
                        width: parent.width - 2 * appTheme.gutter
                        spacing: 2

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Label {
                                text: model.title
                                color: appTheme.label
                                font.family: appTheme.ui
                                renderType: Text.CurveRendering
                                font.pointSize: appTheme.rowSize
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Label {
                                // The ✕ appears where this sits, so the
                                // stamp yields while the card is hovered.
                                // Opacity, not visible: hiding it would
                                // collapse the row and shift the title.
                                text: model.stamp
                                opacity: noteHover.hovered
                                         || xArea.containsMouse ? 0 : 1
                                color: appTheme.label2
                                font.family: appTheme.ui
                                renderType: Text.CurveRendering
                                font.pointSize: appTheme.captionSize
                            }
                        }
                        Label {
                            visible: model.body.length > 0
                            text: model.body
                            color: appTheme.label2
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.subSize
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        // ---- Calls ---------------------------------------------------
        Rectangle {
            color: appTheme.sidebar

            Flickable {
                anchors.fill: parent
                contentHeight: callColumn.implicitHeight + 2 * appTheme.gutter
                clip: true
                ScrollBar.vertical: ScrollBar {}

                ColumnLayout {
                    id: callColumn
                    width: Math.min(parent.width - 2 * appTheme.gutter,
                                    Math.round(620 * appTheme.k))
                    x: (parent.width - width) / 2
                    y: appTheme.gutter
                    spacing: Math.round(18 * appTheme.k)

                    Group {
                        theme: appTheme
                        title: "Place a call"
                        footer: "Call audio routes through this computer's "
                                + "mic and speakers."
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.margins: Math.round(10 * appTheme.k)
                            spacing: Math.round(8 * appTheme.k)
                            RecipientField {
                                id: dialEntry
                                objectName: "dialEntry"
                                Layout.fillWidth: true
                                placeholder: "Contact name or number "
                                             + "e.g. 1 (800) MYAPPLE"
                                onSubmitted: bridge.dial(text)
                            }
                            Button {
                                id: callBtn
                                implicitWidth: Math.round(72 * appTheme.k)
                                implicitHeight: appTheme.fieldHeight
                                onClicked: bridge.dial(dialEntry.text)
                                background: Rectangle {
                                    radius: height / 2
                                    color: callBtn.down ? Qt.darker(appTheme.up, 1.15)
                                                        : appTheme.up
                                }
                                contentItem: Text {
                                    text: "Call"
                                    color: "white"
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.rowSize
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }

                    Group {
                        theme: appTheme
                        title: "Active calls"
                        GroupRow {
                            theme: appTheme
                            label: bridge.callSummary
                            last: true
                            visible: calls.count === 0
                        }
                        Repeater {
                            id: callRepeater
                            model: calls
                            GroupRow {
                                objectName: "callList"
                                theme: appTheme
                                label: model.peer
                                value: model.detail
                                last: index === callRepeater.count - 1
                                Button {
                                    id: answerBtn
                                    objectName: "answerCall"
                                    visible: model.canAnswer
                                    implicitWidth: Math.round(70 * appTheme.k)
                                    implicitHeight: Math.round(28 * appTheme.k)
                                    onClicked: bridge.answer(model.path)
                                    background: Rectangle {
                                        radius: height / 2
                                        color: answerBtn.down
                                               ? Qt.darker(appTheme.up, 1.15) : appTheme.up
                                    }
                                    contentItem: Text {
                                        text: "Answer"; color: "white"
                                        font.family: appTheme.ui
                                        renderType: Text.CurveRendering
                                        font.pointSize: appTheme.captionSize
                                        font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                                Button {
                                    id: hangBtn
                                    objectName: "hangUpCall"
                                    implicitWidth: Math.round(70 * appTheme.k)
                                    implicitHeight: Math.round(28 * appTheme.k)
                                    onClicked: bridge.hangup(model.path)
                                    background: Rectangle {
                                        radius: height / 2
                                        color: hangBtn.down
                                               ? Qt.darker(appTheme.destructive, 1.15)
                                               : appTheme.destructive
                                    }
                                    contentItem: Text {
                                        text: "Hang up"; color: "white"
                                        font.family: appTheme.ui
                                        renderType: Text.CurveRendering
                                        font.pointSize: appTheme.captionSize
                                        font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }
                        }
                    }

                    // A destructive action gets its own card in red, the
                    // way a settings list puts one — not a small outlined
                    // pill floating beside a heading.
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: Math.round(40 * appTheme.k)
                        radius: Math.round(10 * appTheme.k)
                        color: hangAllArea.pressed ? appTheme.pressed : appTheme.canvas
                        opacity: calls.count > 0 ? 1 : 0.45
                        Label {
                            anchors.centerIn: parent
                            text: "Hang up all"
                            color: appTheme.destructive
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.rowSize
                        }
                        MouseArea {
                            id: hangAllArea
                            objectName: "hangUpAll"
                            anchors.fill: parent
                            enabled: calls.count > 0
                            onClicked: bridge.hangupAll()
                        }
                    }
                }
            }
        }

        // ---- Music ---------------------------------------------------
        // Now-playing control over AVRCP. BlueZ publishes the iPhone's
        // player only while the classic audio link is up, so the page
        // has an honest empty state instead of dead controls.
        Rectangle {
            id: musicPage
            color: appTheme.sidebar

            // The daemon reports Position sporadically; the bar advances
            // between reports by asking the bridge to extrapolate, on a
            // 1 Hz tick that only runs while this page can be seen.
            property int posMs: 0
            function syncPos() { posMs = bridge.mediaPositionMs() }
            Component.onCompleted: syncPos()
            Timer {
                interval: 1000; repeat: true
                running: musicPage.visible
                         && bridge.mediaStatus === "playing"
                onTriggered: musicPage.syncPos()
            }
            Connections {
                target: bridge
                function onChanged() { musicPage.syncPos() }
            }

            Flickable {
                id: musicFlick
                anchors.fill: parent
                contentHeight: musicColumn.height + 2 * appTheme.gutter
                clip: true
                ScrollBar.vertical: ScrollBar {}

                ColumnLayout {
                    id: musicColumn
                    width: Math.min(parent.width - 2 * appTheme.gutter,
                                    Math.round(620 * appTheme.k))
                    x: (parent.width - width) / 2
                    y: appTheme.gutter
                    // Explicit height so the art tile below can absorb
                    // the leftover space and the page fills the window;
                    // overflowing content still scrolls via implicit.
                    height: Math.max(implicitHeight,
                                     musicFlick.height
                                     - 2 * appTheme.gutter)
                    spacing: Math.round(18 * appTheme.k)

                    Group {
                        visible: !bridge.mediaAvailable
                        theme: appTheme
                        title: "Now playing"
                        footer: "Controls appear while the iPhone plays "
                                + "audio through this computer."
                        GroupRow {
                            theme: appTheme
                            label: "Nothing playing"
                            last: true
                        }
                    }

                    // Cover art, fetched by the daemon over the AVRCP
                    // image service. Its wrapper takes all the height
                    // the fixed groups below leave over, so the cover
                    // scales to fill the window rather than pooling
                    // empty space under the controls.
                    Item {
                        visible: bridge.mediaAvailable
                                 && bridge.mediaArtPath.length > 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: Math.round(160 * appTheme.k)
                        Rectangle {
                            objectName: "mediaArt"
                            anchors.centerIn: parent
                            width: Math.min(parent.height, parent.width,
                                            Math.round(420 * appTheme.k))
                            height: width
                            radius: Math.round(8 * appTheme.k)
                            color: appTheme.fill
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: bridge.mediaArtPath.length > 0
                                        ? "file://" + bridge.mediaArtPath
                                        : ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                            }
                        }
                    }

                    Group {
                        visible: bridge.mediaAvailable
                        theme: appTheme
                        title: "Now playing"

                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.margins: appTheme.gutter
                            spacing: Math.round(4 * appTheme.k)

                            Label {
                                objectName: "mediaTitle"
                                Layout.fillWidth: true
                                text: bridge.mediaTitle.length > 0
                                      ? bridge.mediaTitle : "Unknown title"
                                color: appTheme.label
                                font.family: appTheme.ui
                                renderType: Text.CurveRendering
                                font.pointSize: appTheme.rowSize
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                            }
                            Label {
                                Layout.fillWidth: true
                                visible: text.length > 0
                                text: bridge.mediaArtist
                                      + (bridge.mediaArtist.length > 0
                                         && bridge.mediaAlbum.length > 0
                                         ? " · " : "")
                                      + bridge.mediaAlbum
                                color: appTheme.label2
                                font.family: appTheme.ui
                                renderType: Text.CurveRendering
                                font.pointSize: appTheme.subSize
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.topMargin: Math.round(8 * appTheme.k)
                                spacing: Math.round(8 * appTheme.k)
                                Label {
                                    text: bridge.formatMs(musicPage.posMs)
                                    color: appTheme.label2
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
                                    Layout.preferredWidth:
                                        Math.ceil(implicitWidth)
                                }
                                // Display only: AVRCP has no seek, so a
                                // draggable bar would be a lie.
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight:
                                        Math.round(4 * appTheme.k)
                                    radius: height / 2
                                    color: appTheme.fill
                                    Rectangle {
                                        objectName: "mediaBar"
                                        anchors.left: parent.left
                                        anchors.top: parent.top
                                        anchors.bottom: parent.bottom
                                        width: parent.width
                                               * (bridge.mediaDurationMs > 0
                                                  ? Math.min(musicPage.posMs
                                                    / bridge.mediaDurationMs,
                                                    1)
                                                  : 0)
                                        radius: parent.radius
                                        color: appTheme.accent
                                    }
                                }
                                Label {
                                    text: bridge.formatMs(
                                              bridge.mediaDurationMs)
                                    color: appTheme.label2
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
                                    Layout.preferredWidth:
                                        Math.ceil(implicitWidth)
                                }
                            }

                            RowLayout {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.topMargin: Math.round(6 * appTheme.k)
                                spacing: Math.round(18 * appTheme.k)

                                Button {
                                    id: prevBtn
                                    objectName: "mediaPrev"
                                    implicitWidth:
                                        Math.round(40 * appTheme.k)
                                    implicitHeight: implicitWidth
                                    onClicked: bridge.mediaPrevious()
                                    background: Rectangle {
                                        radius: height / 2
                                        color: prevBtn.down
                                               ? appTheme.pressed
                                               : appTheme.fill
                                    }
                                    contentItem: Item {
                                        MediaMark {
                                            anchors.centerIn: parent
                                            shape: "prev"
                                            color: appTheme.label
                                            k: appTheme.k
                                        }
                                    }
                                }
                                Button {
                                    id: playBtn
                                    objectName: "mediaPlayPause"
                                    implicitWidth:
                                        Math.round(52 * appTheme.k)
                                    implicitHeight: implicitWidth
                                    onClicked: bridge.mediaPlayPause()
                                    background: Rectangle {
                                        radius: height / 2
                                        color: playBtn.down
                                               ? appTheme.pressed
                                               : appTheme.fill
                                    }
                                    contentItem: Item {
                                        MediaMark {
                                            anchors.centerIn: parent
                                            shape: bridge.mediaStatus
                                                   === "playing"
                                                   ? "pause" : "play"
                                            color: appTheme.label
                                            k: appTheme.k
                                            size: 24
                                        }
                                    }
                                }
                                Button {
                                    id: nextBtn
                                    objectName: "mediaNext"
                                    implicitWidth:
                                        Math.round(40 * appTheme.k)
                                    implicitHeight: implicitWidth
                                    onClicked: bridge.mediaNext()
                                    background: Rectangle {
                                        radius: height / 2
                                        color: nextBtn.down
                                               ? appTheme.pressed
                                               : appTheme.fill
                                    }
                                    contentItem: Item {
                                        MediaMark {
                                            anchors.centerIn: parent
                                            shape: "next"
                                            color: appTheme.label
                                            k: appTheme.k
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Group {
                        visible: bridge.mediaAvailable
                                 && bridge.mediaVolume >= 0
                        theme: appTheme
                        title: "Volume"
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: appTheme.gutter
                            Layout.rightMargin: appTheme.gutter
                            Layout.preferredHeight:
                                Math.round(38 * appTheme.k)
                            Slider {
                                id: volSlider
                                objectName: "mediaVolume"
                                Layout.fillWidth: true
                                from: 0; to: 127; stepSize: 1
                                // Dragging must not fight the daemon's
                                // echo: the model writes the handle only
                                // while it is not held, and drags reach
                                // the daemon debounced.
                                onMoved: volCommit.restart()
                                onPressedChanged: if (!pressed) {
                                    volCommit.stop()
                                    bridge.setMediaVolume(
                                        Math.round(value))
                                }
                            }
                            Binding {
                                target: volSlider
                                property: "value"
                                value: bridge.mediaVolume
                                when: !volSlider.pressed
                            }
                            Timer {
                                id: volCommit
                                interval: 200
                                onTriggered: bridge.setMediaVolume(
                                    Math.round(volSlider.value))
                            }
                        }
                    }

                    Group {
                        visible: bridge.mediaAvailable
                        theme: appTheme
                        title: "Playback"
                        footer: "Whether these take effect is up to the "
                                + "app playing on the iPhone."
                        GroupRow {
                            theme: appTheme
                            label: "Shuffle"
                            Button {
                                id: shuffleBtn
                                objectName: "mediaShuffle"
                                implicitWidth:
                                    Math.round(64 * appTheme.k)
                                implicitHeight:
                                    Math.round(26 * appTheme.k)
                                onClicked: bridge.toggleShuffle()
                                background: Rectangle {
                                    radius: height / 2
                                    color: shuffleBtn.down
                                           ? appTheme.pressed
                                           : appTheme.fill
                                }
                                contentItem: Text {
                                    text: bridge.mediaShuffleText
                                    color: appTheme.label
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                        GroupRow {
                            theme: appTheme
                            label: "Repeat"
                            last: true
                            Button {
                                id: repeatBtn
                                objectName: "mediaRepeat"
                                implicitWidth:
                                    Math.round(64 * appTheme.k)
                                implicitHeight:
                                    Math.round(26 * appTheme.k)
                                onClicked: bridge.toggleRepeat()
                                background: Rectangle {
                                    radius: height / 2
                                    color: repeatBtn.down
                                           ? appTheme.pressed
                                           : appTheme.fill
                                }
                                contentItem: Text {
                                    text: bridge.mediaRepeatText
                                    color: appTheme.label
                                    font.family: appTheme.ui
                                    renderType: Text.CurveRendering
                                    font.pointSize: appTheme.captionSize
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

        // ---- Status --------------------------------------------------
        // A settings-style grouped list: cards of label-and-value rows on
        // the grouped background, each group carrying its explanation as a
        // footer rather than trailing a sentence off every row. Only a
        // problem is coloured — a screen where everything is marked is a
        // screen nobody reads.
        Rectangle {
            color: appTheme.sidebar

            Flickable {
                anchors.fill: parent
                contentHeight: statusColumn.implicitHeight + 2 * appTheme.gutter
                clip: true
                ScrollBar.vertical: ScrollBar {}

                ColumnLayout {
                    id: statusColumn
                    objectName: "statusList"
                    // Constrained and centred rather than edge to edge:
                    // a full-width row leaves its label and its value at
                    // opposite ends of the window with nothing between.
                    width: Math.min(parent.width - 2 * appTheme.gutter,
                                    Math.round(620 * appTheme.k))
                    x: (parent.width - width) / 2
                    y: appTheme.gutter
                    spacing: Math.round(18 * appTheme.k)

                    Repeater {
                        model: bridge.statusGroups
                        Group {
                            required property var modelData
                            theme: appTheme
                            title: modelData.title
                            footer: modelData.footer
                            code: modelData.code
                            Repeater {
                                id: statusRows
                                model: modelData.rows
                                GroupRow {
                                    theme: appTheme
                                    label: modelData.label
                                    value: modelData.value
                                    valueColor: modelData.state === "warn"
                                                ? appTheme.destructive : appTheme.label2
                                    last: index === statusRows.count - 1
                                    // Only rows that carry a bar count
                                    // draw one (cellular).
                                    bars: modelData.bars !== undefined
                                          ? modelData.bars : -1
                                }
                            }
                        }
                    }

                    // Its own card, centred and in the accent colour —
                    // where a settings list puts an action.
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.topMargin: Math.round(4 * appTheme.k)
                        implicitHeight: Math.round(40 * appTheme.k)
                        radius: Math.round(10 * appTheme.k)
                        color: recheckArea.pressed ? appTheme.pressed : appTheme.canvas
                        Label {
                            anchors.centerIn: parent
                            text: "Check again"
                            color: appTheme.accent
                            font.family: appTheme.ui
                            renderType: Text.CurveRendering
                            font.pointSize: appTheme.rowSize
                        }
                        MouseArea {
                            id: recheckArea
                            objectName: "recheck"
                            anchors.fill: parent
                            onClicked: bridge.recheck()
                        }
                    }
                }
            }
        }
    }
}
