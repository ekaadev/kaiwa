import Foundation
import UIKit
import AVFoundation
import Security
import LiveKit
import Shared

final class LiveKitBridge: NSObject, IOSMediaBridge, RoomDelegate {
    private var room: Room?
    private var observer: CallObserver?
    private var intentionalDisconnect = false

    func requestPermission(completion: PermissionCompletion) {
        AVAudioSession.sharedInstance().requestRecordPermission { allowed in
            DispatchQueue.main.async { completion.complete(allowed: allowed) }
        }
    }
    func connectRoom(url: String, token: String, completion: OperationCompletion) {
        intentionalDisconnect = false
        let next = Room(delegate: self)
        room = next
        Task { @MainActor in
            do {
                try await next.connect(url: url, token: token)
                try await next.localParticipant.setMicrophone(enabled: true)
                completion.complete(error: nil)
            } catch { completion.complete(error: "Unable to connect. Check your connection and try again.") }
        }
    }
    func setMuted(muted: Bool, completion: OperationCompletion) {
        Task { @MainActor in
            do {
                guard let room else { completion.complete(error: "No active call"); return }
                try await room.localParticipant.setMicrophone(enabled: !muted)
                completion.complete(error: nil)
            } catch { completion.complete(error: "Microphone state could not be changed.") }
        }
    }
    func disconnectRoom() {
        intentionalDisconnect = true
        let old = room
        room = nil
        Task { await old?.disconnect() }
    }
    func setObserver(listener: CallObserver) { observer = listener }
    func room(_ room: Room, didUpdateConnectionState state: ConnectionState, from oldState: ConnectionState) {
        guard room === self.room else { return }
        DispatchQueue.main.async {
            switch state {
            case .reconnecting: self.observer?.event(state: "Reconnecting")
            case .connected: if oldState == .reconnecting { self.observer?.event(state: "Connected") }
            case .disconnected: if !self.intentionalDisconnect { self.observer?.event(state: "Disconnected") }
            default: break
            }
        }
    }
    func room(_ room: Room, didStartReconnectWithMode reconnectMode: ReconnectMode) {
        DispatchQueue.main.async { self.observer?.event(state: "Reconnecting") }
    }
    func room(_ room: Room, didCompleteReconnectWithMode reconnectMode: ReconnectMode) {
        DispatchQueue.main.async { self.observer?.event(state: "Connected") }
    }
    func room(_ room: Room, didUpdateSpeakingParticipants participants: [LiveKit.Participant]) {
        guard room === self.room else { return }
        let speaking = participants.contains { $0 is RemoteParticipant }
        DispatchQueue.main.async { self.observer?.event(state: speaking ? "Speaking" : "Listening") }
    }
    func room(_ room: Room, participant: RemoteParticipant, didSubscribeTrack publication: RemoteTrackPublication) {
        guard room === self.room, publication.kind == .audio else { return }
        DispatchQueue.main.async { self.observer?.event(state: "remote_audio_subscribed") }
    }
    func room(_ room: Room, participant: RemoteParticipant, didUnsubscribeTrack publication: RemoteTrackPublication) {
        guard room === self.room, publication.kind == .audio else { return }
        DispatchQueue.main.async { self.observer?.event(state: "remote_audio_unsubscribed") }
    }
    func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
    func secret(key: String) -> String? {
        var result: CFTypeRef?
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "conversation.credentials", kSecAttrAccount as String: key, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    func saveSecret(key: String, value: String?) -> Bool {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "conversation.credentials", kSecAttrAccount as String: key]
        guard let value else { let status = SecItemDelete(query as CFDictionary); return status == errSecSuccess || status == errSecItemNotFound }
        let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8), kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let update = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if update == errSecSuccess { return true }
        guard update == errSecItemNotFound else { return false }
        return SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess
    }
}
