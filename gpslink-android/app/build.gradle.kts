plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.example.gpslink"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.example.gpslink"
        minSdk = 24
        targetSdk = 37
        versionCode = 3
        versionName = "1.2"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    // Pipo's wake word, offline. Vosk needs JNA as an .aar (with the native .so files),
    // so the plain jar that Vosk's pom brings in is excluded.
    implementation("com.alphacephei:vosk-android:0.3.75") {
        exclude(group = "net.java.dev.jna")
    }
    implementation("net.java.dev.jna:jna:5.18.1@aar")
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
}