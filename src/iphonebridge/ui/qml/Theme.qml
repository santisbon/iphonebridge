import QtQuick

// Design tokens, in one place, derived from the desktop's own light/dark
// setting. Apple's published system colours are used verbatim rather than
// approximated: they are the vocabulary the rest of the interface speaks,
// and the pairs differ between schemes by more than brightness — systemBlue
// lightens in the dark so it keeps its weight against a dark surface.
QtObject {
    id: theme

    readonly property bool dark: Application.styleHints.colorScheme === Qt.Dark

    // ---- colour ---------------------------------------------------------
    readonly property color accent:      dark ? "#0A84FF" : "#007AFF"
    readonly property color up:          dark ? "#30D158" : "#34C759"
    readonly property color down:        dark ? "#FF9F0A" : "#FF9500"
    readonly property color destructive: dark ? "#FF453A" : "#FF3B30"

    readonly property color canvas:      dark ? "#1C1C1E" : "#FFFFFF"
    readonly property color sidebar:     dark ? "#131315" : "#F2F2F7"
    readonly property color bubbleIn:    dark ? "#3B3B3D" : "#E9E9EB"
    readonly property color bubbleInText: dark ? "#FFFFFF" : "#000000"

    readonly property color label:  dark ? "#FFFFFF" : "#000000"
    readonly property color label2: dark ? "#98989F" : "#8E8E93"
    readonly property color separator: dark ? Qt.rgba(84 / 255, 84 / 255, 88 / 255, 0.40)
                                            : Qt.rgba(60 / 255, 60 / 255, 67 / 255, 0.13)
    readonly property color fill: dark ? Qt.rgba(120 / 255, 120 / 255, 128 / 255, 0.24)
                                       : Qt.rgba(120 / 255, 120 / 255, 128 / 255, 0.12)
    // Transient states — hover, a highlighted menu row, a press — are the
    // surface made lighter or darker, never a colour laid over it. `fill`
    // above is Apple's systemFill, rgb(120,120,128), which carries +8 blue
    // of its own: right for a surface, wrong for a highlight, where it
    // tints whatever it sits on. Plain white and black shift lightness
    // and leave the hue exactly where it was.
    readonly property color hover:   dark ? Qt.rgba(1, 1, 1, 0.09)
                                          : Qt.rgba(0, 0, 0, 0.055)
    readonly property color pressed: dark ? Qt.rgba(1, 1, 1, 0.15)
                                          : Qt.rgba(0, 0, 0, 0.10)

    // ---- type -----------------------------------------------------------
    // One family across every role. Apple's interface does not pair a
    // display face against a text face; it uses one design at different
    // optical sizes, so a second family here would read as a different
    // product. The family is the desktop's own, not a stand-in for SF
    // Pro: this app draws text the way every other application on the
    // desktop does, with nothing of its own in the way.
    function pick(wanted) {
        var have = Qt.fontFamilies()
        for (var i = 0; i < wanted.length; i++)
            if (have.indexOf(wanted[i]) !== -1)
                return wanted[i]
        return Qt.application.font.family
    }

    readonly property string ui: Qt.application.font.family
    // Every text item states its renderType with KDE's own rule
    // (qqc2-desktop-style): Qt's rendering on a fractional display
    // scale, native on an integer one. It has to be per item: on KDE,
    // loading Quick Controls pulls in Kirigami's desktop platform
    // plugin, which flips the process-wide default to native after
    // main() has run — measured live — and native snapped "l" to two
    // solid pixels on a 1.5x display where the desktop's own apps draw
    // it thin. Screen is the item's own screen, so a move re-decides.

    // The exception, and it earns itself: a command you would actually
    // type is the one thing on screen that is code, and it is the one
    // thing set in a monospaced face.
    readonly property string mono: pick(["SF Mono", "Noto Sans Mono",
                                         "DejaVu Sans Mono"])

    // Sizes are points, derived from whatever the desktop asks for, never
    // fixed pixels. Pinning pixels overrode the font size the user chose
    // for every other application: on a 10pt desktop this interface was
    // setting captions at 7.5pt and message text at 9.8pt — smaller than
    // the system UI font, when in Messages the message is the largest
    // text on screen. Emoji inherit the text size, so they were the first
    // thing to become unreadable.
    readonly property real base: Qt.application.font.pointSize > 0
                                 ? Qt.application.font.pointSize : 10

    // One size: the desktop's. Hierarchy is weight and colour, never a
    // ladder of multiples — every text item renders at exactly the size
    // the rest of the desktop's text does.
    // A little above the desktop size for the conversation: the message
    // is the thing being read, so it carries a modest step, with the
    // list and secondary text following it up. Safe to scale now that
    // text is curve-rendered and clean at any size (see `ui` above).
    readonly property real bodySize:    base * 1.15   // the message itself
    readonly property real titleSize:   base * 1.1    // conversation name
    readonly property real rowSize:     base * 1.1    // sender in the list
    readonly property real subSize:     base * 1.05   // previews, secondary
    readonly property real captionSize: base          // stamps, day rules

    // ---- geometry -------------------------------------------------------
    // Anything sized around text scales with it, so a larger desktop font
    // does not clip its own rows.
    readonly property real k: base / 10

    readonly property int bubbleRadius: Math.round(15 * k)
    readonly property int pillRadius:   Math.round(16 * k)
    readonly property int gutter:       Math.round(14 * k)
    readonly property int rowHeight:    Math.round(66 * k)
    readonly property int fieldHeight:  Math.round(34 * k)
    readonly property int cardHeight:   Math.round(60 * k)
    readonly property int markSize:     Math.round(19 * k)
    readonly property real bubbleMax:   0.66  // share of the canvas width
}
