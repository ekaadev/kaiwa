package com.ai.mobile

interface PermissionCompletion {
    fun complete(allowed: Boolean)
}

interface OperationCompletion {
    fun complete(error: String?)
}

interface CallObserver {
    fun event(state: String)
}

/** Implemented by the Swift host; shared code owns all app and call state. */
interface IOSMediaBridge {
    fun requestPermission(completion: PermissionCompletion)
    fun connectRoom(url: String, token: String, completion: OperationCompletion)
    fun setMuted(muted: Boolean, completion: OperationCompletion)
    fun disconnectRoom()
    fun setObserver(listener: CallObserver)
    fun openSettings()
    fun secret(key: String): String?
    fun saveSecret(key: String, value: String?): Boolean
}

object IOSHost {
    var bridge: IOSMediaBridge? = null
    var backAction: (() -> Unit)? = null
    fun back() {
        backAction?.invoke()
    }
}

object AppLifecycle {
    var onBackground: (() -> Unit)? = null
    fun background() {
        onBackground?.invoke()
    }
}
