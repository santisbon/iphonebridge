import QtQuick

// The compose mark: a sheet with its top-right corner open and a pencil
// crossing it. Drawn rather than themed or shipped, for three reasons.
//
// A themed icon (icon.name: "document-edit-symbolic") resolves to whatever
// the desktop draws — Breeze here, Adwaita on GNOME — so the one element
// meant to read as Messages would read as the desktop instead. Shipping an
// SVG fixes that but adds a file to keep in step with the palette. And the
// glyph this echoes, SF Symbols' square.and.pencil, is licensed for Apple's
// platforms and cannot be redistributed, so it is redrawn from the generic
// compose mark rather than traced.
//
// Twelve strokes of Canvas tint with the theme and stay identical
// everywhere.
Canvas {
    id: mark
    property color color: "black"
    // The path below is drawn in an 18-unit box, so both the type scale
    // and any requested size have to reach the canvas transform — raising
    // the item's width alone would only pad it.
    property real k: 1
    property real size: 18
    implicitWidth: Math.round(size * k)
    implicitHeight: Math.round(size * k)
    onKChanged: requestPaint()
    onSizeChanged: requestPaint()
    onColorChanged: requestPaint()

    onPaint: {
        var c = getContext("2d")
        c.reset()
        var u = mark.size / 18 * mark.k
        c.scale(u, u)
        c.strokeStyle = mark.color
        c.lineWidth = 1.6
        c.lineCap = "round"
        c.lineJoin = "round"

        var x0 = 2.5, y0 = 3.5, x1 = 14.5, y1 = 15.5, r = 3

        // The sheet, left open where the pencil crosses it.
        c.beginPath()
        c.moveTo(x1 - 4.5, y0)
        c.lineTo(x0 + r, y0)
        c.arcTo(x0, y0, x0, y0 + r, r)
        c.lineTo(x0, y1 - r)
        c.arcTo(x0, y1, x0 + r, y1, r)
        c.lineTo(x1 - r, y1)
        c.arcTo(x1, y1, x1, y1 - r, r)
        c.lineTo(x1, y0 + 4.5)
        c.stroke()

        // The pencil: shaft, then the ferrule that stops it reading as a
        // bare diagonal.
        c.beginPath()
        c.moveTo(8.2, 9.8)
        c.lineTo(15.8, 2.2)
        c.stroke()

        c.beginPath()
        c.moveTo(10.6, 7.4)
        c.lineTo(13.0, 9.8)
        c.stroke()
    }
}
