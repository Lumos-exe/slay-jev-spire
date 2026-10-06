import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.net.URLClassLoader;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.BiFunction;

/** Read-only candidate-field probe. Does not replace the running bridge, mutate
 * entities, execute choices, or invoke card/relic/monster gameplay callbacks. */
public class ReadNativeFieldsAgentV1 {
    private static Object field(Object value,String name) throws Exception {
        for (Class<?> type=value.getClass();type!=null;type=type.getSuperclass()) {
            try { Field f=type.getDeclaredField(name);f.setAccessible(true);return f.get(value); }
            catch (NoSuchFieldException absent) { }
        }
        throw new NoSuchFieldException(name);
    }
    private static List<Object> sample(Iterable<?> entities,Class<?> base,Method snapshot,
            BiFunction<Class<?>,Object,Object> reference,String idField) throws Exception {
        List<Object> result=new ArrayList<Object>();
        for (Object entity:entities) {
            Map<String,Object> entry=new LinkedHashMap<String,Object>();
            entry.put("id",field(entity,idField));
            if (idField.equals("cardID")) entry.put("uuid",field(entity,"uuid").toString());
            entry.put("native_fields",snapshot.invoke(null,entity,base,reference));
            result.add(entry);
        }
        return result;
    }
    public static void agentmain(final String output,Instrumentation instrumentation) {
        try {
            Class<?> found=null;
            for (Class<?> type:instrumentation.getAllLoadedClasses())
                if (type.getName().equals("com.megacrit.cardcrawl.dungeons.AbstractDungeon")) { found=type;break; }
            if (found==null) throw new IllegalStateException("Game classes unavailable");
            final Class<?> dungeon=found;
            final ClassLoader game=dungeon.getClassLoader();
            Class<?> gdx=Class.forName("com.badlogic.gdx.Gdx",false,game);
            Object app=gdx.getField("app").get(null);
            Class.forName("com.badlogic.gdx.Application",false,game).getMethod("postRunnable",Runnable.class)
                .invoke(app,(Runnable)()-> {
                    Map<String,Object> report=new LinkedHashMap<String,Object>();
                    long started=System.nanoTime();
                    try (URLClassLoader isolated=new URLClassLoader(new java.net.URL[]{
                            ReadNativeFieldsAgentV1.class.getProtectionDomain().getCodeSource().getLocation()},null)) {
                        Class<?> listener=Class.forName("communicationmod.GameStateListener",false,game);
                        if (!Boolean.TRUE.equals(listener.getMethod("isWaitingForCommand").invoke(null)))
                            throw new IllegalStateException("Not at native decision boundary");
                        Method snapshot=isolated.loadClass("jevstate.NativeFields").getMethod(
                            "snapshot",Object.class,Class.class,BiFunction.class);
                        Class<?> card=Class.forName("com.megacrit.cardcrawl.cards.AbstractCard",false,game);
                        BiFunction<Class<?>,Object,Object> reference=(type,value)-> {
                            if (!card.isAssignableFrom(type)) return null;
                            Map<String,Object> ref=new LinkedHashMap<String,Object>();
                            try {
                                ref.put("card_id",value==null ? null : field(value,"cardID"));
                                ref.put("card_uuid",value==null ? null : field(value,"uuid").toString());
                                return ref;
                            } catch (Exception error) { throw new IllegalStateException(error); }
                        };
                        Object player=dungeon.getField("player").get(null);
                        Map<String,Object> samples=new LinkedHashMap<String,Object>();
                        for (String group:Arrays.asList("masterDeck","hand","drawPile","discardPile","exhaustPile"))
                            samples.put(group,sample((Iterable<?>)field(field(player,group),"group"),card,snapshot,reference,"cardID"));
                        samples.put("relics",sample((Iterable<?>)field(player,"relics"),
                            Class.forName("com.megacrit.cardcrawl.relics.AbstractRelic",false,game),snapshot,reference,"relicId"));
                        samples.put("potions",sample((Iterable<?>)field(player,"potions"),
                            Class.forName("com.megacrit.cardcrawl.potions.AbstractPotion",false,game),snapshot,reference,"ID"));
                        Class<?> power=Class.forName("com.megacrit.cardcrawl.powers.AbstractPower",false,game);
                        samples.put("player_powers",sample((Iterable<?>)field(player,"powers"),power,snapshot,reference,"ID"));
                        Iterable<?> monsters=(Iterable<?>)field(dungeon.getMethod("getMonsters").invoke(null),"monsters");
                        samples.put("monsters",sample(monsters,
                            Class.forName("com.megacrit.cardcrawl.monsters.AbstractMonster",false,game),snapshot,reference,"id"));
                        List<Object> powers=new ArrayList<Object>();
                        for (Object monster:monsters) powers.add(sample((Iterable<?>)field(monster,"powers"),power,snapshot,reference,"ID"));
                        samples.put("monster_powers",powers);
                        report.put("samples",samples);
                        report.put("raw_json",Class.forName("communicationmod.GameStateConverter",false,game)
                            .getMethod("getCommunicationState").invoke(null));
                        report.put("status","captured");
                    } catch (Throwable error) { report.put("status","error");report.put("error_type",error.getClass().getSimpleName()); }
                    report.put("elapsed_ms",(System.nanoTime()-started)/1000000.0);
                    try {
                        Class<?> gson=Class.forName("com.autoplay.gson.Gson",false,game);
                        String json=(String)gson.getMethod("toJson",Object.class).invoke(gson.newInstance(),report);
                        Path path=Paths.get(output);Files.createDirectories(path.getParent());
                        Path temporary=path.resolveSibling(path.getFileName()+".tmp");
                        Files.write(temporary,json.getBytes(StandardCharsets.UTF_8));
                        Files.move(temporary,path,StandardCopyOption.REPLACE_EXISTING);
                    } catch (Exception error) { System.err.println("Native field probe report failed: "+error.getClass().getSimpleName()); }
                });
        } catch (Throwable error) { throw new IllegalStateException("Native field probe attach failed",error); }
    }
}
