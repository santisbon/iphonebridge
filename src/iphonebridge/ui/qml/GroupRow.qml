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
    // Signal bars after the value; -1 (the default) draws none. An
    // invisible item costs a layout nothing, so barless rows keep
    // their exact geometry.
    property int bars: -1

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
            renderType: Text.CurveRendering
            font.pointSize: theme.rowSize
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Label {
            visible: row.value.length > 0
            text: row.value
            color: row.valueColor
            font.family: theme.ui
            renderType: Text.CurveRendering
            font.pointSize: theme.rowSize
            // Rounded up, not left to the layout. A label's implicit
            // width is fractional, so its position and its width round
            // separately and the right edge lands a pixel or two off —
            // which reads as a column of values that will not line up.
            Layout.preferredWidth: Math.ceil(implicitWidth)
        }
        SignalBars {
            objectName: "signalBars"
            visible: row.bars >= 0
            theme: row.theme
            bars: row.bars
        }
        RowLayout {
            id: extra
            spacing: Math.round(8 * theme.k)
            // Hidden when empty, so a row with nothing after its value
            // does not still pay the spacing in front of it.
            visible: children.length > 0
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
