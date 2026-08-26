import QtQuick
import QtQuick.Controls

// Named ActionMenu, not ContextMenu: Qt Quick Controls already has a
// ContextMenu type and a file of that name shadows it with something
// that cannot be instantiated.
//
// The right-click menu, styled rather than left to the Basic style and
// whatever the desktop paints on top of it. Unstyled, its highlight came
// from palette roles this interface never sets, so in dark mode it was
// whatever the platform happened to pick.
//
// popupType: Popup.Item keeps it inside the window, which is what makes
// the styling apply at all — a native or windowed popup is drawn by the
// platform and ignores everything below.
Menu {
    id: menu

    property Theme theme
    property string label: ""
    property bool destructive: false
    signal activated()

    popupType: Popup.Item
    padding: Math.round(5 * theme.k)

    background: Rectangle {
        implicitWidth: Math.round(190 * theme.k)
        radius: Math.round(9 * theme.k)
        color: theme.canvas
        border.width: 1
        border.color: theme.separator
    }

    MenuItem {
        id: item
        text: menu.label
        implicitHeight: Math.round(30 * theme.k)
        onTriggered: menu.activated()

        background: Rectangle {
            radius: Math.round(6 * theme.k)
            // The app's own fill, not palette.light. Subtle on purpose:
            // the row underneath is already the thing being acted on.
            color: item.highlighted ? theme.fill : "transparent"
        }
        contentItem: Row {
            spacing: Math.round(8 * theme.k)
            leftPadding: Math.round(8 * theme.k)
            TrashMark {
                visible: menu.destructive
                color: theme.destructive
                k: theme.k
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: item.text
                // Apple colours a destructive action rather than
                // announcing it, so the menu stays quiet until read.
                color: menu.destructive ? theme.destructive : theme.label
                font.family: theme.ui
                font.pointSize: theme.rowSize
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
