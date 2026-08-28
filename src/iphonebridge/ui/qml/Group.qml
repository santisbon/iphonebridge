import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One group of a settings-style list: a small title, a rounded card of
// rows, and an optional footer explaining the group rather than trailing
// a sentence off every row inside it.
//
// Extracted because the Status tab, the Calls tab and the notification
// feed all want exactly this, and three copies drift. Anything placed
// inside a Group lands in the card.
ColumnLayout {
    id: group

    property Theme theme
    property string title: ""
    property string footer: ""
    // A command you would actually type — the one thing on these screens
    // that is code, so the one thing set in a monospaced face.
    property string code: ""

    default property alias content: card.children

    Layout.fillWidth: true
    spacing: Math.round(6 * theme.k)

    Label {
        Layout.leftMargin: theme.gutter
        visible: group.title.length > 0
        text: group.title.toUpperCase()
        color: theme.label2
        font.family: theme.ui
        renderType: Text.CurveRendering
        font.pointSize: theme.captionSize
        font.letterSpacing: 0.7
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: card.implicitHeight
        radius: Math.round(10 * theme.k)
        color: theme.canvas

        ColumnLayout {
            id: card
            width: parent.width
            spacing: 0
        }
    }

    Label {
        Layout.fillWidth: true
        Layout.leftMargin: theme.gutter
        Layout.rightMargin: theme.gutter
        visible: group.footer.length > 0
        text: group.footer
        color: theme.label2
        font.family: theme.ui
        renderType: Text.CurveRendering
        font.pointSize: theme.captionSize
        wrapMode: Text.Wrap
    }

    Label {
        Layout.fillWidth: true
        Layout.leftMargin: theme.gutter
        Layout.rightMargin: theme.gutter
        visible: group.code.length > 0
        text: group.code
        color: theme.label2
        font.family: theme.mono
        renderType: Text.CurveRendering
        font.pointSize: theme.captionSize
        wrapMode: Text.Wrap
    }
}
