import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.List;

/** Activate the game's existing Continue button, only from an observed menu. */
public class ContinueSavedRunAgentV2 {
    private static void report(String path, String value) {
        try { Files.write(Paths.get(path), (value+"\n").getBytes(StandardCharsets.UTF_8),
            StandardOpenOption.CREATE, StandardOpenOption.APPEND); }
        catch (Exception failure) { throw new RuntimeException(failure); }
    }
    public static void agentmain(String reportPath, Instrumentation instrumentation) throws Exception {
        Class<?> communication=null;
        for (Class<?> type:instrumentation.getAllLoadedClasses()) {
            if (!type.getName().equals("communicationmod.CommunicationMod")) continue;
            Field listener=type.getDeclaredField("listener");listener.setAccessible(true);
            if (listener.get(null) instanceof Process) { communication=type;break; }
        }
        if (communication==null) throw new IllegalStateException("No game controller");
        final ClassLoader loader=communication.getClassLoader();
        Object app=Class.forName("com.badlogic.gdx.Gdx",false,loader).getField("app").get(null);
        Class.forName("com.badlogic.gdx.Application",false,loader).getMethod("postRunnable",Runnable.class).invoke(app,(Runnable)()->{
            try {
                String raw=(String)Class.forName("communicationmod.GameStateConverter",false,loader).getMethod("getCommunicationState").invoke(null);
                Class<?> gson=Class.forName("com.autoplay.gson.Gson",false,loader);
                Map<?,?> frame=(Map<?,?>)gson.getMethod("fromJson",String.class,Class.class).invoke(gson.newInstance(),raw,Map.class);
                if (!Boolean.FALSE.equals(frame.get("in_game")) || !((List<?>)frame.get("available_commands")).contains("start"))
                    throw new IllegalStateException("Game is not at its main menu");
                Object menu=Class.forName("com.megacrit.cardcrawl.core.CardCrawlGame",false,loader).getField("mainMenuScreen").get(null);
                for (Object button:(Iterable<?>)menu.getClass().getField("buttons").get(menu)) {
                    if ("RESUME_GAME".equals(button.getClass().getField("result").get(button).toString())) {
                        button.getClass().getMethod("buttonEffect").invoke(button);
                        report(reportPath,"native_continue_clicked=true");return;
                    }
                }
                throw new IllegalStateException("No Continue button; never start a replacement game");
            } catch (Throwable failure) {report(reportPath,"continue_failed="+failure.getClass().getSimpleName());}
        });
    }
}
