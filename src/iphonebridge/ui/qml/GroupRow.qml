import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A row inside a Group: a label, an optional value on the right, and
// whatever else the row needs after it. The hairline stops short of the
// card's left edge, the way a grouped list insets its separators.
ColumnLayout {
    id: row

    property Theme theme
    property string label: ""
    property string value: ""
    property color valueColor: theme.label2
    property bool last: false

    default property alias trailing: extra.children

    Layout.fillWidth: true
    spacing: 0

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: theme.gutter
        Layout.rightMargin: theme.gutter
        Layout.preferredHeight: Math.round(38 * theme.k)
        spacing: Math.round(10 * theme.k)

        Label {
            text: row.label
            color: theme.label
            font.family: theme.ui
            font.pointSize: theme.rowSize
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Label {
            visible: row.value.length > 0
            text: row.value
            color: row.valueColor
            font.family: theme.ui
            font.pointSize: theme.rowSize
        }
        RowLayout {
            id: extra
            spacing: Math.round(8 * theme.k)
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.leftMargin: theme.gutter
        Layout.preferredHeight: 1
        visible: !row.last
        color: theme.separator
    }
}
