// Local macOS AU test host. No microphone or external service is used.
#import <Cocoa/Cocoa.h>
#import <AudioToolbox/AudioToolbox.h>
#import <AudioToolbox/AUCocoaUIView.h>
#include <math.h>
#include <unistd.h>

static AudioUnit unit;
static const UInt32 blockSize = 512;
static NSString *statePath;
static id editorFactory;
static NSView *pluginEditor;
static NSString *referencePath;
static BOOL finishOnSave;
static BOOL liveMode;
static void pumpMessages(NSTimeInterval duration) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:duration];
    while (deadline.timeIntervalSinceNow > 0)
        [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode
                            beforeDate:[NSDate dateWithTimeIntervalSinceNow:MIN(0.02, deadline.timeIntervalSinceNow)]];
}
static NSString *option(NSArray *args, NSString *key) {
    NSUInteger i = [args indexOfObject:key];
    return i != NSNotFound && i + 1 < args.count ? args[i + 1] : nil;
}
static void check(OSStatus status, NSString *operation) {
    if (status != noErr) {
        fprintf(stderr, "%s: OSStatus %d\n", operation.UTF8String, (int)status);
        exit(1);
    }
}
static NSDictionary *captureState(void) {
    CFPropertyListRef value = NULL;
    UInt32 size = sizeof(value);
    check(AudioUnitGetProperty(unit, kAudioUnitProperty_ClassInfo,
                              kAudioUnitScope_Global, 0, &value, &size), @"Get AU state");
    return CFBridgingRelease(value);
}
static BOOL saveState(NSString *path, NSError **error) {
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:captureState()
        format:NSPropertyListXMLFormat_v1_0 options:0 error:error];
    return data && [data writeToFile:path options:NSDataWritingAtomic error:error];
}
static void loadState(NSString *path, NSString *pitchShift) {
    NSError *error;
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:&error];
    id value = data ? [NSPropertyListSerialization propertyListWithData:data
        options:NSPropertyListImmutable format:NULL error:&error] : nil;
    if (![value isKindOfClass:NSDictionary.class]) {
        fprintf(stderr, "Invalid state: %s\n", error.localizedDescription.UTF8String);
        exit(1);
    }
    if (pitchShift || liveMode) {
        char *end = NULL;
        const char *argument = (pitchShift ?: @"0").UTF8String;
        double shift = strtod(argument, &end);
        if (end == argument || *end || !isfinite(shift) || fabs(shift) > 12) {
            fprintf(stderr, "--pitch-semitones requires a number between -12 and 12.\n");
            exit(1);
        }
        // Vocoflex 1.0.3 exports this setting in its full AU state, although
        // it is not an automation parameter. Output F0 was measured to confirm
        // that +8 here means eight semitones, not a normalized parameter value.
        NSData *pluginData = value[@"jucePluginState"];
        NSMutableDictionary *settings = pluginData ? [NSJSONSerialization JSONObjectWithData:pluginData
            options:NSJSONReadingMutableContainers error:&error] : nil;
        if (![settings isKindOfClass:NSMutableDictionary.class] || !settings[@"inputPitchShift"]) {
            fprintf(stderr, "This AU state does not support the tested Vocoflex pitch setting.\n");
            exit(1);
        }
        settings[@"inputPitchShift"] = @(shift);
        if (liveMode) settings[@"useRealtimeLatency"] = @YES;
        NSMutableDictionary *adjusted = [value mutableCopy];
        adjusted[@"jucePluginState"] = [NSJSONSerialization dataWithJSONObject:settings options:0 error:&error];
        value = adjusted;
    }
    CFPropertyListRef ref = (__bridge CFPropertyListRef)value;
    check(AudioUnitSetProperty(unit, kAudioUnitProperty_ClassInfo,
        kAudioUnitScope_Global, 0, &ref, sizeof(ref)), @"Restore AU state");
    // JUCE-based plugins dispatch restoration to the Cocoa message thread.
    // Let it complete before reading parameters or beginning audio processing.
    pumpMessages(2.0);
    // For this installed Vocoflex version, ensure the saved voice sources
    // survived asynchronous restoration. A successful property call alone
    // previously produced a bypass render.
    NSData *expectedData = value[@"jucePluginState"];
    NSData *actualData = captureState()[@"jucePluginState"];
    if (expectedData && actualData) {
        NSDictionary *expected = [NSJSONSerialization JSONObjectWithData:expectedData options:0 error:NULL];
        NSDictionary *actual = [NSJSONSerialization JSONObjectWithData:actualData options:0 error:NULL];
        NSArray *expectedSources = expected[@"voice"][@"sources"];
        NSArray *actualSources = actual[@"voice"][@"sources"];
        if (expectedSources && ![expectedSources isEqual:actualSources]) {
            fprintf(stderr, "Vocoflex voice sources did not restore correctly.\n");
            exit(3);
        }
        if (pitchShift && fabs([expected[@"inputPitchShift"] doubleValue] - [actual[@"inputPitchShift"] doubleValue]) > 0.001) {
            fprintf(stderr, "Vocoflex pitch setting did not restore correctly.\n");
            exit(3);
        }
    }
}
static AudioStreamBasicDescription floatFormat(double sampleRate) {
    AudioStreamBasicDescription f = {0};
    f.mSampleRate = sampleRate;
    f.mFormatID = kAudioFormatLinearPCM;
    f.mFormatFlags = kAudioFormatFlagsNativeFloatPacked | kAudioFormatFlagIsNonInterleaved;
    f.mBytesPerPacket = f.mBytesPerFrame = sizeof(float);
    f.mFramesPerPacket = 1;
    f.mChannelsPerFrame = 2;
    f.mBitsPerChannel = 32;
    return f;
}
static void createUnit(void) {
    AudioComponentDescription desc = {kAudioUnitType_Effect, 'Btwx', 'Manu', 0, 0};
    AudioComponent component = AudioComponentFindNext(NULL, &desc);
    if (!component) { fprintf(stderr, "Vocoflex AU is not installed.\n"); exit(1); }
    check(AudioComponentInstanceNew(component, &unit), @"Create Vocoflex AU");
    AudioStreamBasicDescription format = floatFormat(48000);
    check(AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat,
        kAudioUnitScope_Input, 0, &format, sizeof(format)), @"Set input format");
    check(AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat,
        kAudioUnitScope_Output, 0, &format, sizeof(format)), @"Set output format");
    UInt32 maximum = blockSize;
    check(AudioUnitSetProperty(unit, kAudioUnitProperty_MaximumFramesPerSlice,
        kAudioUnitScope_Global, 0, &maximum, sizeof(maximum)), @"Set block size");
}
static NSView *createEditor(void) {
    UInt32 size; Boolean writable;
    check(AudioUnitGetPropertyInfo(unit, kAudioUnitProperty_CocoaUI,
        kAudioUnitScope_Global, 0, &size, &writable), @"Get AU editor info");
    AudioUnitCocoaViewInfo *info = malloc(size);
    check(AudioUnitGetProperty(unit, kAudioUnitProperty_CocoaUI,
        kAudioUnitScope_Global, 0, info, &size), @"Get AU editor factory");
    NSBundle *bundle = [NSBundle bundleWithURL:(__bridge NSURL *)info->mCocoaAUViewBundleLocation];
    [bundle load];
    Class cls = [bundle classNamed:(__bridge NSString *)info->mCocoaAUViewClass[0]];
    editorFactory = [[cls alloc] init];
    pluginEditor = [(id<AUCocoaUIBase>)editorFactory uiViewForAudioUnit:unit withSize:NSMakeSize(1000, 650)];
    if (!pluginEditor) { fprintf(stderr, "Unable to create Vocoflex editor\n"); exit(1); }
    CFRelease(info->mCocoaAUViewBundleLocation);
    NSUInteger classCount = (size - offsetof(AudioUnitCocoaViewInfo, mCocoaAUViewClass)) / sizeof(CFStringRef);
    for (NSUInteger i = 0; i < classCount; i++) CFRelease(info->mCocoaAUViewClass[i]);
    free(info);
    return pluginEditor;
}
typedef struct {
    float *left, *right;
    UInt64 count, offset;
} Input;
static OSStatus supplyInput(void *context, AudioUnitRenderActionFlags *flags,
    const AudioTimeStamp *time, UInt32 bus, UInt32 frames, AudioBufferList *data) {
    Input *input = context;
    for (UInt32 channel = 0; channel < data->mNumberBuffers; channel++) {
        float *source = channel == 0 ? input->left : input->right;
        float *dest = data->mBuffers[channel].mData;
        if (!dest) return kAudioUnitErr_InvalidPropertyValue;
        for (UInt32 i = 0; i < frames; i++)
            dest[i] = input->offset + i < input->count ? source[input->offset + i] : 0;
        data->mBuffers[channel].mDataByteSize = frames * sizeof(float);
    }
    input->offset += frames;
    return noErr;
}
typedef struct { UInt32 count; AudioBuffer buffers[2]; } StereoBuffers;
static StereoBuffers buffers(float *left, float *right, UInt32 frames) {
    StereoBuffers b = {2, {{1, frames * sizeof(float), left}, {1, frames * sizeof(float), right}}};
    return b;
}
static void render(NSString *inputPath, NSString *outputPath, BOOL paced, double outputGainDB) {
    double outputGain = pow(10, outputGainDB / 20);
    UInt32 offline = paced ? 0 : 1;
    OSStatus offlineStatus = AudioUnitSetProperty(unit, kAudioUnitProperty_OfflineRender,
        kAudioUnitScope_Global, 0, &offline, sizeof(offline));
    if (!paced && offlineStatus != noErr) {
        fprintf(stderr, "AU offline rendering is unsupported (OSStatus %d). Use paced mode.\n", (int)offlineStatus);
        exit(1);
    }
    ExtAudioFileRef source = NULL;
    check(ExtAudioFileOpenURL((__bridge CFURLRef)[NSURL fileURLWithPath:inputPath], &source), @"Open input WAV");
    AudioStreamBasicDescription native;
    UInt32 size = sizeof(native);
    check(ExtAudioFileGetProperty(source, kExtAudioFileProperty_FileDataFormat, &size, &native), @"Read input format");
    // Fixed 48kHz host; ExtAudioFile supplies resampled stereo input.
    AudioStreamBasicDescription format = floatFormat(48000);
    check(ExtAudioFileSetProperty(source, kExtAudioFileProperty_ClientDataFormat,
        sizeof(format), &format), @"Configure input decoder");
    SInt64 nativeFrames;
    size = sizeof(nativeFrames);
    check(ExtAudioFileGetProperty(source, kExtAudioFileProperty_FileLengthFrames,
        &size, &nativeFrames), @"Read input length");
    UInt64 capacity = (UInt64)ceil(nativeFrames * 48000.0 / native.mSampleRate) + blockSize;
    Input input = {calloc(capacity, sizeof(float)), calloc(capacity, sizeof(float)), 0, 0};
    if (!input.left || !input.right) { fprintf(stderr, "Input allocation failed\n"); exit(1); }
    while (input.count < capacity) {
        UInt32 frames = (UInt32)MIN(blockSize, capacity - input.count);
        StereoBuffers b = buffers(input.left + input.count, input.right + input.count, frames);
        check(ExtAudioFileRead(source, &frames, (AudioBufferList *)&b), @"Decode input");
        if (!frames) break;
        input.count += frames;
    }
    ExtAudioFileDispose(source);
    AURenderCallbackStruct callback = {supplyInput, &input};
    check(AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback,
        kAudioUnitScope_Input, 0, &callback, sizeof(callback)), @"Connect input callback");
    check(AudioUnitInitialize(unit), @"Initialize AU");
    Float64 latency = 0, tail = 0;
    size = sizeof(latency);
    check(AudioUnitGetProperty(unit, kAudioUnitProperty_Latency,
        kAudioUnitScope_Global, 0, &latency, &size), @"Read latency");
    size = sizeof(tail);
    AudioUnitGetProperty(unit, kAudioUnitProperty_TailTime, kAudioUnitScope_Global, 0, &tail, &size);
    UInt64 trimFrames = (UInt64)llround(latency * 48000);
    UInt64 total = input.count + trimFrames + (UInt64)ceil(MAX(0, tail) * 48000);
    AudioStreamBasicDescription outputFormat = {0};
    outputFormat.mSampleRate = 48000;
    outputFormat.mFormatID = kAudioFormatLinearPCM;
    outputFormat.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked;
    outputFormat.mBytesPerPacket = outputFormat.mBytesPerFrame = 4;
    outputFormat.mFramesPerPacket = 1;
    outputFormat.mChannelsPerFrame = 2;
    outputFormat.mBitsPerChannel = 16;
    ExtAudioFileRef destination;
    check(ExtAudioFileCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:outputPath],
        kAudioFileWAVEType, &outputFormat, NULL, kAudioFileFlags_EraseFile, &destination), @"Create output WAV");
    check(ExtAudioFileSetProperty(destination, kExtAudioFileProperty_ClientDataFormat,
        sizeof(format), &format), @"Configure output encoder");
    float left[blockSize], right[blockSize];
    double sum = 0, peak = 0;
    UInt64 written = 0;
    for (UInt64 offset = 0; offset < total;) {
        UInt32 frames = (UInt32)MIN(blockSize, total - offset);
        memset(left, 0, sizeof(left)); memset(right, 0, sizeof(right));
        StereoBuffers b = buffers(left, right, frames);
        AudioTimeStamp time = {0}; time.mSampleTime = offset; time.mFlags = kAudioTimeStampSampleTimeValid;
        AudioUnitRenderActionFlags flags = 0;
        check(AudioUnitRender(unit, &flags, &time, 0, frames, (AudioBufferList *)&b), @"Render Vocoflex");
        for (UInt32 i = 0; i < frames; i++) { left[i] *= outputGain; right[i] *= outputGain; }
        UInt32 skip = offset < trimFrames ? (UInt32)MIN(frames, trimFrames - offset) : 0;
        UInt32 count = (UInt32)MIN(frames - skip, input.count - MIN(input.count, written));
        if (count) {
            StereoBuffers selected = buffers(left + skip, right + skip, count);
            check(ExtAudioFileWrite(destination, count, (AudioBufferList *)&selected), @"Write output WAV");
            for (UInt32 i = skip; i < skip + count; i++) {
                sum += left[i] * left[i] + right[i] * right[i];
                peak = MAX(peak, MAX(fabs(left[i]), fabs(right[i])));
            }
            written += count;
        }
        offset += frames;
        if (paced) pumpMessages(frames / 48000.0);
    }
    ExtAudioFileDispose(destination);
    AudioUnitUninitialize(unit);
    free(input.left); free(input.right);
    NSDictionary *result = @{ @"output": outputPath, @"frames": @(written),
        @"sampleRate": @48000, @"latencySeconds": @(latency), @"tailSeconds": @(tail),
        @"peak": @(peak), @"rms": @(written ? sqrt(sum / (written * 2)) : 0),
        @"outputGainDB": @(outputGainDB), @"paced": @(paced) };
    NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:NULL];
    puts([[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
    if (!written || peak < 0.00001) { fprintf(stderr, "Output is silent; conversion not verified.\n"); exit(2); }
}

// Persistent PCM transport: 512-frame stereo float32 blocks at 48 kHz.
// stdout is exclusively audio; readiness and diagnostics use stderr.
static void streamAudio(void) {
    float inLeft[blockSize], inRight[blockSize], outLeft[blockSize], outRight[blockSize];
    float interleaved[blockSize * 2];
    Input input = {inLeft, inRight, blockSize, 0};
    AURenderCallbackStruct callback = {supplyInput, &input};
    check(AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback,
        kAudioUnitScope_Input, 0, &callback, sizeof(callback)), @"Connect live input");
    check(AudioUnitInitialize(unit), @"Initialize live AU");
    Float64 latency = 0; UInt32 size = sizeof(latency);
    check(AudioUnitGetProperty(unit, kAudioUnitProperty_Latency,
        kAudioUnitScope_Global, 0, &latency, &size), @"Read live latency");
    fprintf(stderr, "LIVE_READY %.6f\n", latency); fflush(stderr);
    UInt64 position = 0;
    while (fread(interleaved, sizeof(float), blockSize * 2, stdin) == blockSize * 2) {
        for (UInt32 i = 0; i < blockSize; i++) {
            inLeft[i] = interleaved[i * 2]; inRight[i] = interleaved[i * 2 + 1];
        }
        input.offset = 0;
        StereoBuffers b = buffers(outLeft, outRight, blockSize);
        AudioTimeStamp time = {0}; time.mSampleTime = position; time.mFlags = kAudioTimeStampSampleTimeValid;
        AudioUnitRenderActionFlags flags = 0;
        check(AudioUnitRender(unit, &flags, &time, 0, blockSize, (AudioBufferList *)&b), @"Render live Vocoflex");
        for (UInt32 i = 0; i < blockSize; i++) {
            interleaved[i * 2] = isfinite(outLeft[i]) ? fmaxf(-0.98, fminf(0.98, outLeft[i] * 0.501187f)) : 0;
            interleaved[i * 2 + 1] = isfinite(outRight[i]) ? fmaxf(-0.98, fminf(0.98, outRight[i] * 0.501187f)) : 0;
        }
        if (fwrite(interleaved, sizeof(float), blockSize * 2, stdout) != blockSize * 2) break;
        fflush(stdout);
        position += blockSize;
    }
    AudioUnitUninitialize(unit);
}

@interface LabDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property(strong) NSWindow *window;
@property(strong) NSTextField *status;
@property(strong) id factory;
@end
@implementation LabDelegate
- (void)save:(id)sender {
    if (finishOnSave) {
        NSData *data = captureState()[@"jucePluginState"];
        NSDictionary *settings = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
        if (![settings[@"voice"][@"sources"] count]) {
            self.status.stringValue = @"먼저 오른쪽 Import 버튼으로 참고 음성을 등록해 주세요.";
            return;
        }
    }
    NSError *error;
    if (saveState(statePath, &error)) {
        self.status.stringValue = [@"Saved: " stringByAppendingString:statePath];
        if (finishOnSave) [NSApp terminate:nil];
    }
    else self.status.stringValue = error.localizedDescription;
}
- (void)revealReference:(id)sender {
    [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:referencePath]]];
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSView *editor = pluginEditor ?: createEditor();
    NSSize dimensions = editor.frame.size;
    if (dimensions.width < 100 || dimensions.height < 100) dimensions = NSMakeSize(1000, 650);
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, dimensions.width, dimensions.height + 64)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Hinana Vocoflex Lab";
    self.window.delegate = self;
    editor.frame = NSMakeRect(0, 64, dimensions.width, dimensions.height);
    [self.window.contentView addSubview:editor];
    NSButton *save = [NSButton buttonWithTitle:(finishOnSave ? @"등록 저장" : @"Save AU State") target:self action:@selector(save:)];
    save.frame = NSMakeRect(12, 32, 140, 26);
    [self.window.contentView addSubview:save];
    if (referencePath) {
        NSButton *reveal = [NSButton buttonWithTitle:@"참고 파일 보기" target:self action:@selector(revealReference:)];
        reveal.frame = NSMakeRect(162, 32, 140, 26);
        [self.window.contentView addSubview:reveal];
    }
    self.status = [NSTextField labelWithString:referencePath ?
        [NSString stringWithFormat:@"오른쪽 Import 버튼으로 %@을 등록한 뒤 ‘등록 저장’을 누르세요.", referencePath.lastPathComponent] :
        @"Import a reference voice, choose a cursor position, then save."];
    self.status.frame = NSMakeRect(12, 6, dimensions.width - 24, 22);
    self.status.font = [NSFont systemFontOfSize:11];
    [self.window.contentView addSubview:self.status];
    [self.window center]; [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSArray *args = NSProcessInfo.processInfo.arguments;
        if ([args containsObject:@"--quit-standalone"]) {
            NSArray *apps = [NSRunningApplication runningApplicationsWithBundleIdentifier:@"com.dreamtonics.vocoflex"];
            for (NSRunningApplication *app in apps) [app terminate];
            NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:15];
            while (deadline.timeIntervalSinceNow > 0) {
                BOOL running = NO;
                for (NSRunningApplication *app in apps) running |= !app.terminated;
                if (!running) return 0;
                pumpMessages(0.1);
            }
            fprintf(stderr, "Vocoflex did not close. Save or dismiss its open dialog, then retry.\n");
            return 1;
        }
        if (args.count == 1) {
            NSString *directory = [NSBundle.mainBundle.bundlePath stringByDeletingLastPathComponent];
            NSMutableArray *defaults = [NSMutableArray arrayWithArray:args];
            [defaults addObjectsFromArray:@[@"--editor", @"--save-state",
                [directory stringByAppendingPathComponent:@"editor-session.aupreset"]]];
            NSString *reference = [directory stringByAppendingPathComponent:@"hinana.aupreset"];
            if ([NSFileManager.defaultManager fileExistsAtPath:reference])
                [defaults addObjectsFromArray:@[@"--state", reference]];
            args = defaults;
        }
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        createUnit();
        createEditor();
        liveMode = [args containsObject:@"--stream"];
        NSString *load = option(args, @"--state");
        NSString *pitchShift = option(args, @"--pitch-semitones");
        if (pitchShift && !load) { fprintf(stderr, "--pitch-semitones requires --state.\n"); return 1; }
        if (load) loadState(load, pitchShift);
        for (NSArray *p in @[@[@"--cursor-x", @1586587119], @[@"--cursor-y", @1586587120]]) {
            NSString *value = option(args, p[0]);
            if (value) {
                float v = value.floatValue;
                if (!isfinite(v) || v < -2 || v > 2) { fprintf(stderr, "Cursor outside -2..2\n"); return 1; }
                // Vocoflex 1.0.3's AU publishes -2..2 but its accessor uses
                // normalized 0..1 values (verified against saved coordinates).
                check(AudioUnitSetParameter(unit, [p[1] unsignedIntValue], kAudioUnitScope_Global, 0, (v + 2) / 4, 0), p[0]);
            }
        }
        pumpMessages(0.1);
        NSString *input = option(args, @"--input"), *output = option(args, @"--output");
        if ([args containsObject:@"--editor"]) {
            referencePath = option(args, @"--reference");
            finishOnSave = [args containsObject:@"--finish-on-save"];
            statePath = option(args, @"--save-state");
            if (!statePath) { fprintf(stderr, "--editor requires --save-state PATH\n"); return 1; }
            [NSApplication sharedApplication];
            [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
            LabDelegate *delegate = [LabDelegate new];
            NSApp.delegate = delegate;
            [NSApp run];
        } else if (liveMode) {
            if (!load) { fprintf(stderr, "--stream requires --state\n"); return 1; }
            streamAudio();
        } else if (input && output) {
            NSString *gainText = option(args, @"--output-gain-db");
            double gainDB = 0;
            if (gainText) {
                const char *argument = gainText.UTF8String;
                char *end = NULL;
                gainDB = strtod(argument, &end);
                if (end == argument || *end || !isfinite(gainDB) || gainDB < -60 || gainDB > 0) {
                    fprintf(stderr, "--output-gain-db requires a number between -60 and 0.\n");
                    return 1;
                }
            }
            render(input, output, ![args containsObject:@"--fast"], gainDB);
            NSString *save = option(args, @"--save-state");
            NSError *error;
            if (save && !saveState(save, &error)) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
        } else {
            NSError *error;
            NSString *save = option(args, @"--save-state");
            if (save && !saveState(save, &error)) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
            for (NSNumber *param in @[@1586587119, @1586587120]) {
                AudioUnitParameterValue value;
                check(AudioUnitGetParameter(unit, param.unsignedIntValue, kAudioUnitScope_Global, 0, &value), @"Read cursor");
                printf("%u: cursor coordinate %.8f (AU value %.8f)\n", param.unsignedIntValue, value * 4 - 2, value);
            }
        }
        AudioComponentInstanceDispose(unit);
    }
    return 0;
}
