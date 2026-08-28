import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Emoji picker for the composer: search on top, a recents tab, then
// the full set — categories, names and search keywords all read from
// the system's emoji dictionary through the bridge, none of it shipped
// with the app. Stays open for repeated picks; Escape or a click
// outside closes it.
Popup {
    id: picker

    property Theme theme
    signal picked(string emoji)

    // The platform must not draw this as a native window, or the
    // styling is ignored.
    popupType: Popup.Item
    // Takes focus while open so typing goes to the search field and
    // Escape lands here; the opener refocuses the composer on close.
    focus: true
    width: Math.round(392 * theme.k)
    height: Math.round(380 * theme.k)
    padding: Math.round(8 * theme.k)
    background: Rectangle {
        radius: Math.round(10 * theme.k)
        color: theme.canvas
        border.width: 1
        border.color: theme.separator
    }

    // Loaded on first open, not at startup: the database is thousands
    // of entries and nobody pays for it before asking for it.
    property var groups: []
    // 0 = recents, 1.. = groups[i-1].
    property int catIndex: 0
    readonly property bool searching:
        searchField.text.trim().length >= 2
    property var results: []

    onAboutToShow: {
        if (groups.length === 0)
            groups = bridge.emojiGroups
        catIndex = bridge.emojiRecents.length > 0 ? 0 : 1
    }
    onOpened: searchField.forceActiveFocus()
    onClosed: searchField.text = ""

    contentItem: ColumnLayout {
        spacing: Math.round(6 * picker.theme.k)

        TextField {
            id: searchField
            objectName: "emojiSearch"
            Layout.fillWidth: true
            implicitHeight: Math.round(30 * picker.theme.k)
            placeholderText: "Search"
            color: picker.theme.label
            placeholderTextColor: picker.theme.label2
            font.family: picker.theme.ui
            renderType: Text.CurveRendering
            font.pointSize: picker.theme.subSize
            leftPadding: Math.round(10 * picker.theme.k)
            rightPadding: Math.round(10 * picker.theme.k)
            background: Rectangle {
                radius: height / 2
                color: picker.theme.fill
                border.width: searchField.activeFocus ? 1 : 0
                border.color: picker.theme.accent
            }
            // Computed from the text itself, not from `searching`: that
            // property is bound to this same text and may not have
            // re-evaluated when this handler runs.
            onTextChanged: picker.results =
                text.trim().length >= 2 ? bridge.searchEmoji(text) : []
            Keys.onEscapePressed: picker.close()
        }

        Row {
            visible: !picker.searching
            Layout.alignment: Qt.AlignHCenter
            spacing: 1

            component CatTab: Rectangle {
                property bool current: false
                property string glyph: ""
                signal tapped()
                width: Math.round(36 * picker.theme.k)
                height: width
                radius: Math.round(8 * picker.theme.k)
                color: current ? picker.theme.fill
                       : tabTap.containsMouse ? picker.theme.hover
                                              : "transparent"
                Text {
                    anchors.centerIn: parent
                    text: parent.glyph
                    font.pointSize: picker.theme.rowSize * 1.25
                }
                MouseArea {
                    id: tabTap
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: parent.tapped()
                }
            }

            CatTab {
                glyph: "⏱️"
                current: picker.catIndex === 0
                onTapped: picker.catIndex = 0
            }
            Repeater {
                model: picker.groups
                CatTab {
                    required property var modelData
                    required property int index
                    glyph: modelData.icon
                    current: picker.catIndex === index + 1
                    onTapped: picker.catIndex = index + 1
                }
            }
        }

        GridView {
            id: grid
            objectName: "emojiGrid"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            cellWidth: Math.round(48 * picker.theme.k)
            cellHeight: cellWidth
            model: picker.searching ? picker.results
                   : picker.catIndex === 0 ? bridge.emojiRecents
                   : picker.groups[picker.catIndex - 1] !== undefined
                     ? picker.groups[picker.catIndex - 1].emoji : []
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                required property string modelData
                width: grid.cellWidth - 2
                height: grid.cellHeight - 2
                radius: Math.round(6 * picker.theme.k)
                color: cellTap.containsMouse ? picker.theme.hover
                                             : "transparent"
                Text {
                    anchors.centerIn: parent
                    text: parent.modelData
                    font.pointSize: picker.theme.rowSize * 2.2
                }
                MouseArea {
                    id: cellTap
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: picker.picked(parent.modelData)
                }
            }

            Label {
                anchors.centerIn: parent
                visible: grid.count === 0
                width: parent.width - Math.round(24 * picker.theme.k)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: picker.searching ? "No matches"
                      : picker.groups.length === 0
                        ? "No emoji data — install the ibus-data package"
                        : "Nothing recent yet"
                color: picker.theme.label2
                font.family: picker.theme.ui
                renderType: Text.CurveRendering
                font.pointSize: picker.theme.subSize
            }
        }
    }
}
