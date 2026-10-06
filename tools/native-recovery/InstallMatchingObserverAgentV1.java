import java.lang.instrument.Instrumentation;
import java.net.URLClassLoader;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

/** Installs an observation-only subscriber; does not redefine game classes. */
public class InstallMatchingObserverAgentV1 {
    public static void agentmain(final String output,Instrumentation instrumentation) throws Exception {
        Class<?> dungeon=null;
        for (Class<?> type:instrumentation.getAllLoadedClasses())
            if (type.getName().equals("com.megacrit.cardcrawl.dungeons.AbstractDungeon")) { dungeon=type;break; }
        if (dungeon==null) throw new IllegalStateException("No loaded game");
        final ClassLoader game=dungeon.getClassLoader();
        Class<?> gdx=Class.forName("com.badlogic.gdx.Gdx",false,game);
        Object app=gdx.getField("app").get(null);
        Class.forName("com.badlogic.gdx.Application",false,game).getMethod("postRunnable",Runnable.class)
            .invoke(app,(Runnable)()-> {
                try {
                    URLClassLoader child=new URLClassLoader(new java.net.URL[]{
                        InstallMatchingObserverAgentV1.class.getProtectionDomain().getCodeSource().getLocation()},game);
                    child.loadClass("jevstate.MatchingGameObservation").getMethod("installSidecar",String.class).invoke(null,output);
                    Files.write(Paths.get(output+".installed"),"installed".getBytes(StandardCharsets.UTF_8));
                } catch (Exception error) {
                    try { Files.write(Paths.get(output+".error"),error.getClass().getSimpleName().getBytes(StandardCharsets.UTF_8)); }
                    catch (Exception ignored) { }
                }
            });
    }
}
