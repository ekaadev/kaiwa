import UIKit
import SwiftUI
import Shared

struct ComposeView: UIViewControllerRepresentable {
    func makeUIViewController(context: Self.Context) -> UIViewController {
        IOSHost.shared.bridge = LiveKitBridge()
        let controller = MainViewControllerKt.MainViewController()
        let gesture = UIScreenEdgePanGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.backGesture(_:)))
        gesture.edges = .left
        controller.view.addGestureRecognizer(gesture)
        return controller
    }

    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator: NSObject {
        @objc func backGesture(_ recognizer: UIScreenEdgePanGestureRecognizer) {
            if recognizer.state == .ended && recognizer.translation(in: recognizer.view).x > 50 {
                IOSHost.shared.back()
            }
        }
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Self.Context) {}
}

struct ContentView: View {
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        ComposeView()
            .ignoresSafeArea()
            .onChange(of: scenePhase) { _, phase in
                if phase == .background { AppLifecycle.shared.background() }
            }
    }
}