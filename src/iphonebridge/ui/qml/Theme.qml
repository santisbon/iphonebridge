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
    readonly property color selected: dark ? Qt.rgba(120 / 255, 120 / 255, 128 / 255, 0.32)
                                           : Qt.rgba(120 / 255, 120 / 255, 128 / 255, 0.16)

    // ---- type -----------------------------------------------------------
    // One family across every role. Apple's interface does not pair a
    // display face against a text face; it uses one design at different
    // optical sizes, so a second family here would read as a different
    // product. Inter is the closest widely-packaged face to SF Pro — it was
    // drawn for interfaces at small sizes — and the desktop's own sans
    // stands in when it is absent.
    function pick(wanted) {
        var have = Qt.fontFamilies()
        for (var i = 0; i < wanted.length; i++)
            if (have.indexOf(wanted[i]) !== -1)
                return wanted[i]
        return Qt.application.font.family
    }

    readonly property string ui: pick(["Inter", "SF Pro Text", "Adwaita Sans"])
    // The exception, and it earns itself: the Setup tab is a readout of
    // daemon health and counts, which is the one place Apple would set in
    // SF Mono.
    readonly property string mono: pick(["SF Mono", "Noto Sans Mono",
                                         "DejaVu Sans Mono"])

    readonly property int titleSize:   15   // conversation name
    readonly property int rowSize:     13   // sender in the list
    readonly property int bodySize:    13   // message text, previews
    readonly property int captionSize: 10   // timestamps, day rules, the ribbon

    // ---- geometry -------------------------------------------------------
    readonly property int bubbleRadius: 15
    readonly property int pillRadius:   16
    readonly property int gutter:       14
    readonly property real bubbleMax:   0.66  // share of the canvas width
}
