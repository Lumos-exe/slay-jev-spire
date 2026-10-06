import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Read native tooltip registries on the game thread; no effects or redefinitions. */
public class ReadKeywordRegistryAgentV1 {
    public static void agentmain(final String destination, Instrumentation instrumentation) {
        try {
            Class<?> found=null;
            for (Class<?> type:instrumentation.getAllLoadedClasses())
                if (type.getName().equals("com.megacrit.cardcrawl.helpers.GameDictionary")) { found=type;break; }
            if (found==null) throw new IllegalStateException("Dictionary not initialized");
            final Class<?> dictionary=found;
            final ClassLoader loader=dictionary.getClassLoader();
            Class<?> gdx=Class.forName("com.badlogic.gdx.Gdx",false,loader);
            Object app=gdx.getField("app").get(null);
            Class.forName("com.badlogic.gdx.Application",false,loader).getMethod("postRunnable",Runnable.class).invoke(app,(Runnable) () -> {
                try {
                    Map<String,Object> data=new TreeMap<String,Object>();
                    data.put("source","Live GameDictionary and CardLibrary; read-only snapshot");
                    data.put("keywords",new TreeMap<Object,Object>((Map<?,?>)dictionary.getField("keywords").get(null)));
                    data.put("keyword_parents",new TreeMap<Object,Object>((Map<?,?>)dictionary.getField("parentWord").get(null)));
                    Map<String,Object> cards=new TreeMap<String,Object>();
                    Class<?> library=Class.forName("com.megacrit.cardcrawl.helpers.CardLibrary",false,loader);
                    for (Map.Entry<?,?> entry:((Map<?,?>)library.getField("cards").get(null)).entrySet()) {
                        Object card=entry.getValue();
                        Object terms=card.getClass().getField("keywords").get(card);
                        if (terms instanceof Collection) cards.put(String.valueOf(entry.getKey()),new ArrayList<Object>((Collection<?>)terms));
                    }
                    data.put("card_keywords",cards);
                    Class<?> gson=Class.forName("com.autoplay.gson.Gson",true,loader);
                    String json=(String)gson.getMethod("toJson",Object.class).invoke(gson.getDeclaredConstructor().newInstance(),data);
                    Path path=Paths.get(destination);Files.createDirectories(path.getParent());
                    Files.write(path,json.getBytes(StandardCharsets.UTF_8));
                } catch (Throwable error) { failure(destination,error); }
            });
        } catch (Throwable error) { failure(destination,error); }
    }
    private static void failure(String path,Throwable error) {
        try { Files.write(Paths.get(path),("{\"error\":\""+error.getClass().getSimpleName()+"\"}").getBytes(StandardCharsets.UTF_8)); }
        catch (Exception ignored) { }
    }
}
