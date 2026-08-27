import QtQuick

// Cellular signal as the phone draws it: ascending bars, filled up to
// the reported level, the rest dimmed. Four bars, like the phone's own
// status bar: the HFP indicator has room for 0-5, but iOS sends the
// bar count it displays (0-4), so a fifth bar here could never fill
// and read as permanently missing signal.
Row {
    id: sig

    property Theme theme
    // Filled bars, 0..total; anything negative draws nothing.
    property int bars: 0
    property int total: 4

    spacing: Math.round(2 * theme.k)
    visible: bars >= 0

    Repeater {
        model: sig.total
        Rectangle {
            required property int index
            width: Math.round(3 * sig.theme.k)
            height: Math.round((5 + index * 2) * sig.theme.k)
            anchors.bottom: parent.bottom
            radius: width / 2
            color: index < sig.bars ? sig.theme.label
                                    : sig.theme.fill
        }
    }
}
