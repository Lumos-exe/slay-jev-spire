package jevstate;

import basemod.BaseMod;
import basemod.interfaces.PostInitializeSubscriber;
import com.evacipated.cardcrawl.modthespire.lib.SpireInitializer;
import com.autoplay.gson.Gson;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.helpers.CardLibrary;
import com.megacrit.cardcrawl.helpers.RelicLibrary;
import com.megacrit.cardcrawl.helpers.GameDictionary;
import com.megacrit.cardcrawl.core.Settings;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Export registered content from the running game. Never a legality whitelist.
 * Prototype values are explicitly separate from authoritative live instances.
 */
@SpireInitializer
public final class NativeCatalog implements PostInitializeSubscriber {
    private static final TreeMap<String,Object> cards=new TreeMap<String,Object>();
    private static final TreeMap<String,Object> relics=new TreeMap<String,Object>();
    private static final ArrayList<Object> failures=new ArrayList<Object>();
    private static boolean initialized;

    public static void initialize() { BaseMod.subscribe(new NativeCatalog()); }

    public static Map<String,String> keywordDescriptions(AbstractCard card) {
        Map<String,String> result=new TreeMap<String,String>();
        for (String keyword:card.keywords) {
            String description=GameDictionary.keywords.get(keyword);
            if (description!=null) result.put(keyword,description);
        }
        return result;
    }

    private static Map<String,Object> cardDefinition(AbstractCard card, boolean upgrade) {
        Map<String,Object> result=new TreeMap<String,Object>();
        result.put("id",card.cardID); result.put("name",card.name);
        result.put("type",card.type.toString()); result.put("color",card.color.toString());
        result.put("rarity",card.rarity.toString()); result.put("target_type",card.target.toString());
        result.put("base_cost",card.cost); result.put("base_damage",card.baseDamage);
        result.put("base_block",card.baseBlock); result.put("base_magic_number",card.baseMagicNumber);
        result.put("raw_description",card.rawDescription); result.put("upgrades",card.timesUpgraded);
        result.put("exhausts",card.exhaust); result.put("ethereal",card.isEthereal);
        result.put("innate",card.isInnate); result.put("self_retain",card.selfRetain);
        ArrayList<String> tags=new ArrayList<String>();
        for (Object tag:card.tags) tags.add(tag.toString());
        result.put("tags",tags);
        result.put("keywords",new ArrayList<String>(new TreeSet<String>(card.keywords)));
        result.put("keyword_descriptions",keywordDescriptions(card));
        result.put("native_mechanics",NativeMechanics.describe(card,AbstractCard.class));
        result.put("prototype_native_fields",CardValues.nativeFields(card,AbstractCard.class));
        if (upgrade) {
            try {
                result.put("can_upgrade",card.canUpgrade());
                if (card.canUpgrade()) {
                    AbstractCard copy=card.makeStatEquivalentCopy(); copy.upgrade();
                    result.put("upgrade",cardDefinition(copy,false));
                }
            } catch (RuntimeException unsupported) {
                result.put("upgrade_unknown",unsupported.getClass().getSimpleName());
                failures.add("card_upgrade:"+card.cardID+":"+unsupported.getClass().getSimpleName());
            }
        }
        return result;
    }

    private static Map<String,Object> relicDefinition(AbstractRelic relic) {
        Map<String,Object> result=new TreeMap<String,Object>();
        result.put("id",relic.relicId); result.put("name",relic.name);
        result.put("tier",relic.tier.toString()); result.put("description",relic.description);
        result.put("native_mechanics",NativeMechanics.describe(relic,AbstractRelic.class));
        result.put("prototype_native_fields",CardValues.nativeFields(relic,AbstractRelic.class));
        return result;
    }

    @Override public void receivePostInitialize() {
        if (System.getProperty("jev.catalog.path")==null) return;
        for (AbstractCard card:CardLibrary.cards.values()) {
            try { cards.put(card.cardID,cardDefinition(card,true)); }
            catch (RuntimeException error) { failures.add("card:"+card.cardID+":"+error.getClass().getSimpleName()); }
        }
        // All registry maps, including each character's pool, without a relic ID list.
        for (Field field:RelicLibrary.class.getDeclaredFields()) {
            if (!Modifier.isStatic(field.getModifiers()) || !Map.class.isAssignableFrom(field.getType())) continue;
            try {
                field.setAccessible(true);
                for (Object value:((Map<?,?>)field.get(null)).values()) {
                    if (value instanceof AbstractRelic) {
                        AbstractRelic relic=(AbstractRelic)value;
                        relics.put(relic.relicId,relicDefinition(relic));
                    }
                }
            } catch (ReflectiveOperationException | RuntimeException error) {
                failures.add("relic_registry:"+field.getName()+":"+error.getClass().getSimpleName());
            }
        }
        initialized=true;write();
    }

    public static void observe(AbstractCard card) {
        if (!initialized || cards.containsKey(card.cardID)) return;
        Map<String,Object> record=cardDefinition(card,false);
        record.put("source","observed_instance_not_registry_prototype");
        cards.put(card.cardID,record);write();
    }

    public static void observe(AbstractRelic relic) {
        if (!initialized || relics.containsKey(relic.relicId)) return;
        Map<String,Object> record=relicDefinition(relic);record.put("source","observed_instance");
        relics.put(relic.relicId,record);write();
    }

    private static void write() {
        Map<String,Object> document=new TreeMap<String,Object>();
        document.put("schema_version",1); document.put("bridge_version","0.4.5");
        document.put("language",Settings.language.toString());
        document.put("source","Live CardLibrary and RelicLibrary registries, plus newly observed instances");
        document.put("scope","Base definitions and one native upgrade. Live costs, counters, powers and legal actions override prototypes. Callback metadata is not full executable effect semantics.");
        document.put("registered_card_count",CardLibrary.cards.size());
        document.put("cards",cards);document.put("relics",relics);document.put("failures",failures);
        document.put("keywords",new TreeMap<String,String>(GameDictionary.keywords));
        document.put("keyword_parents",new TreeMap<String,String>(GameDictionary.parentWord));
        document.put("keyword_source","Live GameDictionary tooltip registry; native exceptions remain in card, power and relic descriptions");
        try {
            Path destination=Paths.get(System.getProperty("jev.catalog.path"));
            Files.createDirectories(destination.getParent());
            Path temporary=destination.resolveSibling(destination.getFileName().toString()+".tmp");
            Files.write(temporary,new Gson().toJson(document).getBytes(StandardCharsets.UTF_8));
            try { Files.move(temporary,destination,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE); }
            catch (AtomicMoveNotSupportedException unavailable) { Files.move(temporary,destination,StandardCopyOption.REPLACE_EXISTING); }
        } catch (Exception error) { System.err.println("Native catalog export failed: "+error.getClass().getSimpleName()); }
    }
}
