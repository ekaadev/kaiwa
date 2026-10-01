package com.ai.mobile

interface Platform {
    val name: String
}

expect fun getPlatform(): Platform