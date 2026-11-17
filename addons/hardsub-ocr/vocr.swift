// macOS Vision OCR parancssori segéd a hardsub-ocr add-onhoz.
//
// Az ocr_subs.py fordítja le (swiftc) és futtatja; kézzel nem kell hívni.
//
//   vocr <nyelv>[,<nyelv>…]  < képútvonalak (soronként egy)
//   vocr --supported           a Vision által ismert nyelvek (JSON-lista)
//
// Kimenet: bemenetenként (a bemenet sorrendjében) egy JSON-sor:
//   [["szöveg", 0.98], ["másik sor", 0.5]]     — a felismert sorok, megbízhatósággal
//   null                                        — a kép nem olvasható
// A szöveget nem tördeljük és nem szűrjük: ez a Python-oldal dolga.

import Foundation
import ImageIO
import Vision

func newRequest() -> VNRecognizeTextRequest {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    return req
}

func emit(_ obj: Any) {
    if let data = try? JSONSerialization.data(withJSONObject: obj),
       let s = String(data: data, encoding: .utf8) {
        print(s)
    } else {
        print("null")
    }
    fflush(stdout)
}

let arg = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "zh-Hans"
if arg == "--supported" {
    emit((try? newRequest().supportedRecognitionLanguages()) ?? [])
    exit(0)
}
let langs = arg.split(separator: ",").map(String.init)

func recognize(_ path: String) -> [[Any]]? {
    let url = URL(fileURLWithPath: path) as CFURL
    guard let src = CGImageSourceCreateWithURL(url, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return nil }
    let req = newRequest()
    req.recognitionLanguages = langs
    do {
        try VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
    } catch {
        return nil
    }
    return (req.results ?? []).compactMap { $0.topCandidates(1).first }
        .map { [$0.string, Double($0.confidence)] }
}

while let line = readLine(strippingNewline: true) {
    if line.isEmpty { continue }
    if let rows = recognize(line) {
        emit(rows)
    } else {
        print("null")
        fflush(stdout)
    }
}
