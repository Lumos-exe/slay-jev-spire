import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

/** Invokes CommunicationMod's existing controller restart, on the render thread.
 * Does not redefine classes, change combat state, or inject game commands. */
public class RestartCommunicationAgentV3 {
    private static void report(String path, String message) {
        try {
            Files.write(Paths.get(path), (message + "\n").getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Exception ignored) { }
    }
    public static void agentmain(final String reportPath, Instrumentation instrumentation) {
        try {
            Class<?> communication = null, base = null, gdx = null;
            for (Class<?> type : instrumentation.getAllLoadedClasses()) {
                if (type.getName().equals("communicationmod.CommunicationMod")) {
                    try {
                        Field process = type.getDeclaredField("listener");
                        process.setAccessible(true);
                        if (process.get(null) instanceof Process) { communication = type; break; }
                    } catch (Throwable unavailable) { }
                }
            }
            if (communication != null) {
                base = Class.forName("basemod.BaseMod", false, communication.getClassLoader());
                gdx = Class.forName("com.badlogic.gdx.Gdx", false, communication.getClassLoader());
            }
            if (communication == null || base == null || gdx == null)
                throw new IllegalStateException("Required game mods are not loaded");
            Object subscriber = null;
            for (Field field : base.getDeclaredFields()) {
                if (!Modifier.isStatic(field.getModifiers())) continue;
                field.setAccessible(true);
                Object value = field.get(null);
                if (value instanceof Iterable) {
                    for (Object item : (Iterable<?>) value) {
                        if (communication.isInstance(item)) { subscriber = item; break; }
                    }
                }
                if (subscriber != null) break;
            }
            if (subscriber == null) throw new IllegalStateException("Existing mod subscriber not found");
            final Object instance = subscriber;
            final Class<?> mod = communication;
            final Method restart = mod.getDeclaredMethod("startExternalProcess");
            restart.setAccessible(true);
            final Class<?> listener = Class.forName("communicationmod.GameStateListener", false, mod.getClassLoader());
            Object app = gdx.getField("app").get(null);
            Class<?> application = Class.forName("com.badlogic.gdx.Application", false, gdx.getClassLoader());
            application.getMethod("postRunnable", Runnable.class).invoke(app, (Runnable) () -> {
                try {
                    if (!Boolean.TRUE.equals(listener.getMethod("isWaitingForCommand").invoke(null)))
                        throw new IllegalStateException("Game is not at a stable command boundary");
                    // CommunicationMod caches SpireConfig. Restarting alone
                    // otherwise launches the old command even after an atomic
                    // release-path change in config.properties.
                    Field configField = mod.getDeclaredField("communicationConfig");
                    configField.setAccessible(true);
                    Object config = configField.get(null);
                    config.getClass().getMethod("load").invoke(config);
                    Object ok = restart.invoke(instance);
                    mod.getField("mustSendGameState").setBoolean(null, true);
                    report(reportPath, "controller_restart=" + ok);
                } catch (Exception error) {
                    report(reportPath, "restart_failed=" + error.getClass().getSimpleName());
                }
            });
            report(reportPath, "restart_queued");
        } catch (Throwable error) {
            report(reportPath, "attach_failed=" + error.getClass().getSimpleName());
        }
    }
}
