import QtQuick

// Transport glyphs for the Music tab: play, pause, next, prev. Drawn on
// Canvas for the same reasons as ComposeMark — themed icons read as the
// desktop, and unicode media glyphs depend on font coverage. Filled
// triangles and bars, drawn in an 18-unit box centred on (9, 9).
Canvas {
    id: mark
    property color color: "black"
    property real k: 1
    property real size: 18
    // "play" | "pause" | "next" | "prev"
    property string shape: "play"
    implicitWidth: Math.round(size * k)
    implicitHeight: Math.round(size * k)
    onKChanged: requestPaint()
    onSizeChanged: requestPaint()
    onColorChanged: requestPaint()
    onShapeChanged: requestPaint()

    onPaint: {
        var c = getContext("2d")
        c.reset()
        var u = mark.size / 18 * mark.k
        c.scale(u, u)
        c.fillStyle = mark.color
        c.lineJoin = "round"

        function tri(x0, xTip) {
            // Triangle spanning y 4.5..13.5, pointing toward xTip.
            c.beginPath()
            c.moveTo(x0, 4.5)
            c.lineTo(x0, 13.5)
            c.lineTo(xTip, 9)
            c.closePath()
            c.fill()
        }
        function bar(x) {
            c.fillRect(x, 4.5, 2.2, 9)
        }

        if (mark.shape === "play") {
            // Nudged right so the visual centre sits on the button centre.
            tri(6.2, 13.8)
        } else if (mark.shape === "pause") {
            bar(5.3)
            bar(10.5)
        } else if (mark.shape === "next") {
            tri(3.6, 9.6)
            tri(9.4, 15.4)
        } else if (mark.shape === "prev") {
            // Mirrored: triangles point left.
            c.beginPath()
            c.moveTo(8.6, 4.5)
            c.lineTo(8.6, 13.5)
            c.lineTo(2.6, 9)
            c.closePath()
            c.fill()
            c.beginPath()
            c.moveTo(14.4, 4.5)
            c.lineTo(14.4, 13.5)
            c.lineTo(8.4, 9)
            c.closePath()
            c.fill()
        }
    }
}
