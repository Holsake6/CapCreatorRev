import Foundation
import AVFoundation
import Vision

struct Output: Codable {
    let duration: Double
    let sampledFrames: Int
    let humanFrameRatio: Double
    let faceFrameRatio: Double
    let meanFrameDistance: Double
    let labelDiversity: Int
    let labels: [String: Double]

    enum CodingKeys: String, CodingKey {
        case duration
        case sampledFrames = "sampled_frames"
        case humanFrameRatio = "human_frame_ratio"
        case faceFrameRatio = "face_frame_ratio"
        case meanFrameDistance = "mean_frame_distance"
        case labelDiversity = "label_diversity"
        case labels
    }
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

guard CommandLine.arguments.count == 2 else { fail("usage: video_visual_analyzer VIDEO") }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let asset = AVURLAsset(url: url)
let semaphore = DispatchSemaphore(value: 0)
var durationSeconds = 0.0
Task {
    do {
        let duration = try await asset.load(.duration)
        durationSeconds = max(0.1, CMTimeGetSeconds(duration))
    } catch {
        fail("cannot read video duration: \(error)")
    }
    semaphore.signal()
}
semaphore.wait()

let sampleCount = max(5, min(12, Int(ceil(durationSeconds / 1.5))))
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = CMTime(seconds: 0.15, preferredTimescale: 600)
generator.requestedTimeToleranceAfter = CMTime(seconds: 0.15, preferredTimescale: 600)

var humanFrames = 0
var faceFrames = 0
var labelScores: [String: [Double]] = [:]
var distances: [Double] = []
var previousFeature: VNFeaturePrintObservation?
var completed = 0

for index in 0..<sampleCount {
    let fraction = (Double(index) + 0.5) / Double(sampleCount)
    let time = CMTime(seconds: durationSeconds * fraction, preferredTimescale: 600)
    guard let image = try? generator.copyCGImage(at: time, actualTime: nil) else { continue }
    completed += 1

    let classify = VNClassifyImageRequest()
    let pose = VNDetectHumanBodyPoseRequest()
    let faces = VNDetectFaceRectanglesRequest()
    let feature = VNGenerateImageFeaturePrintRequest()
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try? handler.perform([classify, pose, faces, feature])

    if let observations = pose.results, !observations.isEmpty { humanFrames += 1 }
    if let observations = faces.results, !observations.isEmpty { faceFrames += 1 }
    for item in (classify.results ?? []).prefix(8) where item.confidence >= 0.08 {
        labelScores[item.identifier.lowercased(), default: []].append(Double(item.confidence))
    }
    if let current = feature.results?.first {
        if let previous = previousFeature {
            var distance: Float = 0
            if (try? current.computeDistance(&distance, to: previous)) != nil {
                distances.append(Double(distance))
            }
        }
        previousFeature = current
    }
}

guard completed > 0 else { fail("no frames extracted") }
let labels = labelScores.mapValues { values in
    values.reduce(0, +) / Double(values.count)
}.sorted { $0.value > $1.value }.prefix(20).reduce(into: [String: Double]()) { result, item in
    result[item.key] = (item.value * 1000).rounded() / 1000
}
let meanDistance = distances.isEmpty ? 0 : distances.reduce(0, +) / Double(distances.count)
let output = Output(
    duration: (durationSeconds * 100).rounded() / 100,
    sampledFrames: completed,
    humanFrameRatio: (Double(humanFrames) / Double(completed) * 1000).rounded() / 1000,
    faceFrameRatio: (Double(faceFrames) / Double(completed) * 1000).rounded() / 1000,
    meanFrameDistance: (meanDistance * 1000).rounded() / 1000,
    labelDiversity: labels.count,
    labels: labels
)
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
guard let data = try? encoder.encode(output) else { fail("cannot encode result") }
print(String(data: data, encoding: .utf8)!)
