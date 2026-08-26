import QtQuick
import QtQuick.Controls

// The right-click menu.
//
// Styling the MenuItem is not enough on its own. Whichever Quick Controls
// style the desktop provides also owns the Menu's internal ListView, and
// org.kde.breeze — the style in use here — gives that list a highlight
// item painted from the Kirigami selection colour. It is drawn *over* the
// MenuItem, so a row styled underneath was simply covered, and the
// highlight read blue on a light surface and green on a dark one.
//
// Replacing contentItem with a list that has no highlight of its own is
// what fixes it. A Menu rather than a Popup: keyboard navigation, Escape,
// the focus grab and the menu's accessibility role all come with it.
Menu {
    id: menu

    property Theme theme
    property string label: ""
    property bool destructive: false
    signal activated()

    // In-scene, not a native or separate-window popup — a menu drawn by
    // the platform ignores everything below.
    popupType: Popup.Item
    padding: Math.round(5 * theme.k)

    // Opened where the pointer is, which is what Menu.popup(pos) does;
    // named so the call sites read as an intent rather than an overload.
    function popupAt(pos) {
        popup(pos)
    }

    contentItem: ListView {
        implicitHeight: contentHeight
        implicitWidth: Math.round(150 * theme.k)
        model: menu.contentModel
        currentIndex: menu.currentIndex
        keyNavigationWraps: true
        interactive: false
        clip: true
        // The whole point: the row paints its own state.
        highlight: null
    }

    background: Rectangle {
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
            // The surface, lightened — never a colour laid over it.
            color: item.highlighted ? theme.hover : "transparent"
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
