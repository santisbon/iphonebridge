import QtQuick

// A trash can, drawn for the same reasons as the compose mark: a themed
// icon would be whatever the desktop draws, and Apple's own glyph is
// licensed for Apple's platforms. Tints with whatever colour it is given,
// which here is always the destructive red.
Canvas {
    id: mark
    property color color: "black"
    property real k: 1
    implicitWidth: Math.round(16 * k)
    implicitHeight: Math.round(16 * k)
    onColorChanged: requestPaint()
    onKChanged: requestPaint()

    onPaint: {
        var c = getContext("2d")
        c.reset()
        c.scale(mark.k, mark.k)
        c.strokeStyle = mark.color
        c.lineWidth = 1.3
        c.lineCap = "round"
        c.lineJoin = "round"

        // Lid, and the handle sitting on it.
        c.beginPath()
        c.moveTo(2.2, 4.4)
        c.lineTo(13.8, 4.4)
        c.stroke()

        c.beginPath()
        c.moveTo(6.2, 4.4)
        c.lineTo(6.2, 2.6)
        c.lineTo(9.8, 2.6)
        c.lineTo(9.8, 4.4)
        c.stroke()

        // Body, tapering the way a bin does.
        c.beginPath()
        c.moveTo(3.6, 4.4)
        c.lineTo(4.4, 13.4)
        c.lineTo(11.6, 13.4)
        c.lineTo(12.4, 4.4)
        c.stroke()

        // The two ribs.
        c.beginPath()
        c.moveTo(6.6, 6.6)
        c.lineTo(6.9, 11.2)
        c.moveTo(9.4, 6.6)
        c.lineTo(9.1, 11.2)
        c.stroke()
    }
}
