import QtQuick
import QtQuick.Controls

// The right-click menu — a Popup, deliberately not a Menu.
//
// A Menu's list belongs to whichever Quick Controls style the desktop
// provides (org.kde.breeze here), and that style gives it a highlight item
// painted from the Kirigami selection colour. It draws over whatever the
// MenuItem's background says, so the row read blue in light and green
// against a dark surface no matter how it was styled underneath.
// Overriding the background, replacing contentItem, and clearing
// `highlight` after construction all left it in place.
//
// A Popup has no list of its own, so everything here is ours.
Popup {
    id: menu

    property Theme theme
    property string label: ""
    property bool destructive: false
    signal activated()

    padding: Math.round(5 * theme.k)
    modal: false
    dim: false
    closePolicy: Popup.CloseOnPressOutside | Popup.CloseOnEscape
    popupType: Popup.Item

    // Opened where the pointer is, the way a context menu should be.
    function popupAt(pos) {
        x = pos.x
        y = pos.y
        open()
    }

    background: Rectangle {
        radius: Math.round(9 * theme.k)
        color: theme.canvas
        border.width: 1
        border.color: theme.separator
    }

    contentItem: Rectangle {
        implicitWidth: Math.round(150 * theme.k)
        implicitHeight: Math.round(30 * theme.k)
        radius: Math.round(6 * theme.k)
        // The surface, lightened — never a colour laid over it.
        color: area.containsMouse ? theme.hover : "transparent"

        Row {
            anchors.left: parent.left
            anchors.leftMargin: Math.round(9 * theme.k)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Math.round(8 * theme.k)
            TrashMark {
                visible: menu.destructive
                color: theme.destructive
                k: theme.k
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: menu.label
                // Apple colours a destructive action rather than
                // announcing it, so the menu stays quiet until read.
                color: menu.destructive ? theme.destructive : theme.label
                font.family: theme.ui
                font.pointSize: theme.rowSize
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: { menu.close(); menu.activated() }
        }
    }
}
