# AI Conversation mobile

A light-mode Material 3 Expressive app with shared Compose Multiplatform UI and call orchestration for Android and iOS. The primary layout targets a portrait 412×892dp phone; scrollable content, system insets, and keyboard padding keep controls reachable on smaller displays.

## Using the app

Open Testing to read the participation agreement in a bottom sheet. **Agree and continue** requests microphone permission through the operating system, registers the participant through `/v1/study/participants`, and saves the returned resume token securely. **Decline** performs no registration or permission request. Registration does not start or record a call; once setup succeeds, select **Start to Call**. Existing device credentials restore progress automatically. Settings contains microphone access and participation information; it has no server or token input.

The current short consent copy is a development draft. The research owner must approve the consent text/version and retention policy before enrolling real participants. Registration and progress require only the backend and database. AI/model availability is required for calls, and unavailable calls do not complete a study session.

Home requests the native microphone permission when **Start to Call** is selected, without a consent sheet. If access is denied in Home or Testing, a snackbar that closes automatically after about eight seconds explains the requirement and offers **Settings**, which opens the app's system settings. During Testing enrollment, this snackbar floats over the agreement area inside the modal window, above the Agree/Decline actions. It does not add a row below Decline or change the sheet height. All snackbars use an 8 dp corner radius. Settings and dismiss actions remain available; accessibility settings can extend the timeout. No microphone settings button or permission error card is added to the agreement. The sheet remains open for retry; registration does not proceed until permission is granted. Every call attempt checks the current system permission again, including after restarting the app. A grant in Home is shared with Testing and vice versa; existing grants do not display another permission prompt. Android may suppress the system dialog after repeated denials, in which case Settings is the recovery path. Revoked or expired one-time permission is checked again on the next attempt.

Once microphone access is granted and the call service is ready, speak about any topic. The tutor understands English/Japanese and replies in Japanese. Hang Up stops your microphone and requests a normal server ending. The white outlined microphone control at the bottom right mutes/unmutes. The unlabeled red control centered above it ends the call. Calls stop when the app moves into the background; these are recorded as interrupted locally. System Back offers an end-call confirmation.

Session contains actual local transcripts, including incomplete transcripts from failed calls. Search their contents, select a conversation to read it, retry a pending transcript download, or confirm local deletion. Local deletion does not delete researcher-managed evidence on the server. There is no bundled sample history, simulated tutor, or client-controlled study completion.

## Structure

- `shared/commonMain`: Material 3 theme, screens, state, Ktor API, Room entities/DAO, DataStore settings, and platform bridge contracts.
- `shared/androidMain`: LiveKit Android 2.29.0, runtime microphone permission, encrypted Keystore-backed credentials, native Room/DataStore paths, system Back.
- `shared/iosMain` and `iosApp`: shared persistence with a Swift LiveKit 2.17.0 and Keychain bridge. The Swift host includes an edge Back gesture.
- `../backend`: control API, Pipecat transcript capture, private study recordings, and migration `0003_study_evidence`.

## Backend address and local development

Use `deliverables/ai-conversation-1.0.11-local.apk` for current development. It includes the automatic mobile enrollment flow and is configured for the computer's localhost backend through USB port forwarding. When the deployed backend is ready, rebuild with its HTTPS address using the command below; no server or token input is needed in the app.

The temporary **Preview call screen** action has been removed from Home and Testing. Use **Start to Call** to enter the approved Call Screen once microphone access is granted and the backend call service is ready.

The endpoint is supplied at build time through `-PconversationServerUrl=...` or the
`CONVERSATION_SERVER_URL` environment variable. No address is bundled by default, because there is
currently no live deployment. An unconfigured build shows an unavailable message and creates no
participant or sample token. Release builds accept HTTPS; HTTP is enabled only for development builds.
Legacy manually entered URLs are no longer used; credentials already saved for the configured
endpoint remain available.

For Android on a USB-connected phone, run the lightweight backend on the computer at port 8000,
then forward the phone's loopback port:

```sh
adb reverse tcp:8000 tcp:8000
./gradlew :androidApp:assembleDebug -PconversationServerUrl=http://127.0.0.1:8000
```

The local build uses package `com.ai.mobile.debug` and can coexist with the release app. Port
forwarding must be set up again if the connection is lost. No model or GPU is required to register
participants or retrieve progress. The normal backend database/migrations must still be configured.
For a future deployed HTTPS backend:

```sh
./gradlew :androidApp:assembleRelease -PconversationServerUrl=https://your-backend.example
```

For an iOS debug build, supply a local hostname reachable from the phone through the same Gradle
property/environment variable. Local networking is enabled in the native host; release Kotlin rejects
HTTP endpoints. The Swift host still needs verification on macOS.

## Backend setup

Deploy the backend with the existing LiveKit, Whisper, Qwen, and Kokoro configuration. Before upgrading an existing database, take a backup, then run:

```sh
cd ../backend
uv run alembic upgrade head
```

Study calls additionally require an approved explicit retention policy and a private durable recording directory:

```sh
STUDY_EVIDENCE_DIR=/absolute/private/path
STUDY_RETENTION_DAYS=<approved-number-of-days>
```

The directory must have mode 700 and must not be served over HTTP. Normal study endings require at least 120 seconds of server-received microphone PCM plus successful finalization of user/tutor audio, transcript/timing events, and checksummed manifest. Configure HTTPS in front of the control API. Practice data stays out of research storage. See the backend README for the full configuration and limitations.

## Build and checks

```sh
./gradlew :shared:testAndroidHostTest :shared:compileKotlinIosArm64 :shared:compileKotlinIosSimulatorArm64 :androidApp:lintRelease :androidApp:assembleRelease
```

Configuration cache is enabled in `gradle.properties`. The app configuration generator declares managed task inputs and outputs so its action can be serialized; Android debug builds have been checked for both cache storage and reuse. Android host tests use Robolectric; no emulator or device is required. Shared iOS Kotlin compilation runs on this Linux host; Swift/Xcode compilation and iOS simulator tests require macOS. Open `iosApp/iosApp.xcodeproj` on macOS to resolve the pinned Swift package and build the native host.

If the host runs out of memory, build one target at a time with one worker and a 2 GB heap. For the current localhost APK:

```sh
./gradlew :androidApp:assembleDebug -PconversationServerUrl=http://127.0.0.1:8000 --max-workers=1 --no-daemon '-Dorg.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8' -Pkotlin.compiler.execution.strategy=in-process
```

Roboto weights and Material Symbols Rounded are bundled offline. Icons use vector outlines from the bundled Material Symbols to keep them centered independently of text baselines and font scaling. Font licenses are in `licenses/`.

## Release signing

A dedicated RSA-3072 PKCS12 release key is stored in `.signing/conversation-release.p12`, with private Gradle signing configuration in `.signing/release.properties`. Both are excluded from source control and restricted to the owner. Back up both securely; future APK updates must use the same key. Do not commit or share the properties file. For another checkout, restore these files and update `storeFile` to the restored keystore's absolute path before building.

The release APK is minified and resource-shrunk. `deliverables/` contains the signed APK, SHA-256 checksum, certificate details, and validation report. Live calls require a configured running backend. Build/host tests do not establish real inference quality, network audio delivery, or what was audibly played on a phone.
