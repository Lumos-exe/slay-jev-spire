package jevstate;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePrefixPatch;
import com.evacipated.cardcrawl.modthespire.lib.SpireReturn;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.core.AbstractCreature;
import com.megacrit.cardcrawl.powers.AbstractPower;
import com.megacrit.cardcrawl.relics.AbstractRelic;
import com.megacrit.cardcrawl.potions.AbstractPotion;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.monsters.AbstractMonster;
import com.megacrit.cardcrawl.rooms.AbstractRoom;
import java.util.ArrayList;
import java.util.HashMap;

@SpirePatch(cls="communicationmod.GameStateConverter", method="convertCardToJson",
            paramtypez={AbstractCard.class})
public class CardValues {
    public static java.util.Map<String,Object> nativeFields(Object instance, Class<?> base) {
        java.util.function.BiFunction<Class<?>,Object,Object> reference=(type,value)-> {
            if (!AbstractCard.class.isAssignableFrom(type)) return null;
            HashMap<String,Object> ref=new HashMap<String,Object>();
            AbstractCard card=(AbstractCard)value;
            ref.put("card_id",card==null ? null : card.cardID);
            ref.put("card_uuid",card==null ? null : card.uuid.toString());
            return ref;
        };
        return communicationmod.GameStateListener.isWaitingForCommand()
            ? NativeFields.atRevision(instance,base,ActionProtocol.ledger.currentRevision(),reference)
            : NativeFields.snapshot(instance,base,reference);
    }
    private static boolean benchmarkNormalized = false;
    @SpirePatch(clz=com.megacrit.cardcrawl.neow.NeowEvent.class, method="buttonEffect", paramtypez={int.class})
    public static class BenchmarkNeow {
        @SpirePrefixPatch
        public static SpireReturn<Void> prefix(com.megacrit.cardcrawl.neow.NeowEvent __instance, int buttonPressed) {
            if (!Boolean.getBoolean("jev.benchmark")) return SpireReturn.Continue();
            AbstractDungeon.getCurrRoom().phase = AbstractRoom.RoomPhase.COMPLETE;
            AbstractDungeon.closeCurrentScreen();
            AbstractDungeon.dungeonMapScreen.open(false);
            return SpireReturn.Return(null);
        }
    }
    @SpirePatch(clz=com.megacrit.cardcrawl.characters.AbstractPlayer.class, method="preBattlePrep")
    public static class BenchmarkSetup {
        @SpirePrefixPatch
        public static void prefix(com.megacrit.cardcrawl.characters.AbstractPlayer __instance) {
            if (!Boolean.getBoolean("jev.benchmark") || AbstractDungeon.floorNum != 1) return;
            com.megacrit.cardcrawl.core.Settings.FAST_MODE = true;
            __instance.maxHealth = 80;
            __instance.currentHealth = 80;
            __instance.masterDeck.group.clear();
            for (int i = 0; i < 5; i++) __instance.masterDeck.addToBottom(com.megacrit.cardcrawl.helpers.CardLibrary.getCard("Strike_R").makeCopy());
            for (int i = 0; i < 4; i++) __instance.masterDeck.addToBottom(com.megacrit.cardcrawl.helpers.CardLibrary.getCard("Defend_R").makeCopy());
            __instance.masterDeck.addToBottom(new com.megacrit.cardcrawl.cards.red.Bash());
            __instance.relics.clear();
            __instance.relics.add(new com.megacrit.cardcrawl.relics.BurningBlood());
            __instance.potionSlots = 3;
            __instance.potions.clear();
            for (int i = 0; i < 3; i++) __instance.potions.add(new com.megacrit.cardcrawl.potions.PotionSlot(i));
            benchmarkNormalized = true;
        }
    }
    @SpirePostfixPatch
    public static HashMap<String, Object> postfix(HashMap<String, Object> __result, AbstractCard card) {
        NativeCatalog.observe(card);
        __result.put("native_mechanics", NativeMechanics.describe(card, AbstractCard.class));
        __result.put("native_fields", nativeFields(card, AbstractCard.class));
        __result.put("keywords",new ArrayList<String>(new java.util.TreeSet<String>(card.keywords)));
        __result.put("keyword_descriptions",NativeCatalog.keywordDescriptions(card));
        HashMap<String, Object> values = new HashMap<String, Object>();
        boolean inHand = AbstractDungeon.player != null && AbstractDungeon.player.hand.group.contains(card);
        values.put("source", "game_card_fields");
        values.put("scope", inHand ? "current_hand_card_fields" : "base_card_stats");
        values.put("damage", inHand ? card.damage : card.baseDamage);
        values.put("block", inHand ? card.block : card.baseBlock);
        values.put("magic_number", inHand ? card.magicNumber : card.baseMagicNumber);
        values.put("base_damage", card.baseDamage);
        values.put("base_block", card.baseBlock);
        values.put("base_magic_number", card.baseMagicNumber);
        values.put("cost_for_turn", card.costForTurn);
        values.put("free_to_play",inHand && card.freeToPlay());
        values.put("damage_modified", card.isDamageModified);
        values.put("block_modified", card.isBlockModified);
        values.put("magic_number_modified", card.isMagicNumberModified);
        __result.put("native_values", values);
        __result.put("raw_description", card.rawDescription);
        __result.put("target_type", card.target.toString());
        __result.put("free_to_play_once", card.freeToPlayOnce);
        __result.put("exhaust_on_use_once", card.exhaustOnUseOnce);
        __result.put("retain", card.retain);
        __result.put("self_retain", card.selfRetain);
        __result.put("purge_on_use", card.purgeOnUse);
        __result.put("can_upgrade", card.canUpgrade());
        if (card.canUpgrade()) {
            AbstractCard upgraded = card.makeStatEquivalentCopy();
            upgraded.upgrade();
            HashMap<String, Object> preview = new HashMap<String, Object>();
            preview.put("cost", upgraded.costForTurn);
            preview.put("base_damage", upgraded.baseDamage);
            preview.put("base_block", upgraded.baseBlock);
            preview.put("magic_number", upgraded.magicNumber);
            preview.put("upgrades", upgraded.timesUpgraded);
            preview.put("name", upgraded.name);
            preview.put("raw_description", upgraded.rawDescription);
            preview.put("type", upgraded.type.toString());
            preview.put("target_type", upgraded.target.toString());
            preview.put("exhausts", upgraded.exhaust);
            preview.put("ethereal", upgraded.isEthereal);
            preview.put("retain", upgraded.retain);
            preview.put("self_retain", upgraded.selfRetain);
            __result.put("upgrade_preview", preview);
        }
        if (inHand && AbstractDungeon.getCurrRoom() != null
                && AbstractDungeon.getCurrRoom().phase == AbstractRoom.RoomPhase.COMBAT) {
            ArrayList<Integer> validTargets = new ArrayList<Integer>();
            int targetIndex = 0;
            for (AbstractMonster monster : AbstractDungeon.getMonsters().monsters) {
                if (!monster.isDeadOrEscaped() && !monster.halfDead && card.canUse(AbstractDungeon.player, monster))
                    validTargets.add(targetIndex);
                targetIndex++;
            }
            __result.put("valid_target_indices", validTargets);
        }
        if (AbstractDungeon.player != null && AbstractDungeon.getCurrRoom() != null
                && AbstractDungeon.getCurrRoom().phase == AbstractRoom.RoomPhase.COMBAT
                && inHand && card.baseDamage >= 0) {
            ArrayList<Object> previews = new ArrayList<Object>();
            try {
                int index = 0;
                for (AbstractMonster monster : AbstractDungeon.getMonsters().monsters) {
                    if (!monster.isDead && !monster.isDying && !monster.isEscaping && !monster.halfDead) {
                        AbstractCard copy = card.makeStatEquivalentCopy();
                        copy.applyPowers();
                        copy.calculateCardDamage(monster);
                        HashMap<String, Object> preview = new HashMap<String, Object>();
                        preview.put("target_index", index);
                        preview.put("damage_before_block", copy.multiDamage != null && index < copy.multiDamage.length ? copy.multiDamage[index] : copy.damage);
                        preview.put("source", "game_calculateCardDamage");
                        preview.put("scope", "current_state_damage_calculation_not_action_simulation");
                        previews.add(preview);
                    }
                    index++;
                }
                __result.put("target_damage_previews", previews);
            } catch (RuntimeException failure) {
                __result.put("damage_preview_status", "unavailable");
            }
        }
        return __result;
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getGridState")
    public static class GridSelection {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            if (AbstractDungeon.gridSelectScreen.confirmScreenUp) {
                try {
                    java.lang.reflect.Field hovered = com.megacrit.cardcrawl.screens.select.GridCardSelectScreen.class.getDeclaredField("hoveredCard");
                    hovered.setAccessible(true);
                    AbstractCard card = (AbstractCard) hovered.get(AbstractDungeon.gridSelectScreen);
                    if (card != null) __result.put("pending_card_uuid", card.uuid.toString());
                } catch (ReflectiveOperationException unavailable) {
                    __result.put("pending_card_unknown", true);
                }
            }
            return __result;
        }
    }

    @SpirePatch(clz=com.megacrit.cardcrawl.screens.select.GridCardSelectScreen.class, method="cancelUpgrade")
    public static class GridCancelBoundary {
        @SpirePostfixPatch
        public static void postfix() {
            // The native input has completed, but stays on GRID with zero
            // selected cards. Publish the missing event through the original
            // readiness path; do not infer completion from arbitrary changes.
            communicationmod.GameStateListener.registerStateChange();
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getScreenState")
    public static class NativeOptions {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            if (__result!=null && __result.containsKey("event_id")) {
                try {
                    java.util.Map<String,Object> view=MatchingGameObservation.capture();
                    if (view!=null) __result.put("native_event",view);
                } catch (ReflectiveOperationException | RuntimeException error) {
                    __result.put("native_event_error",error.getClass().getSimpleName());
                }
            }
            if (__result == null || !__result.containsKey("rest_options")) return __result;
            try {
                Class<?> choices = Class.forName("communicationmod.ChoiceScreenUtils");
                java.lang.reflect.Method buttons = choices.getDeclaredMethod("getValidRestRoomButtons");
                java.lang.reflect.Method name = choices.getDeclaredMethod("getCampfireOptionName",
                    com.megacrit.cardcrawl.ui.campfire.AbstractCampfireOption.class);
                buttons.setAccessible(true); name.setAccessible(true);
                HashMap<String, Object> details = new HashMap<String, Object>();
                for (Object button : (Iterable<?>) buttons.invoke(null)) {
                    HashMap<String, Object> item = new HashMap<String, Object>();
                    item.put("description", NativeFields.read(button, "description"));
                    details.put((String) name.invoke(null, button), item);
                }
                __result.put("rest_option_details", details);
            } catch (ReflectiveOperationException unavailable) {
                __result.put("rest_details_unknown", true);
                __result.put("rest_details_error", unavailable.getClass().getSimpleName());
            }
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getGameState")
    public static class NativeRunContext {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            com.megacrit.cardcrawl.map.MapRoomNode node = AbstractDungeon.getCurrMapNode();
            if (node != null) {
                HashMap<String, Object> coordinates = new HashMap<String, Object>();
                coordinates.put("x", node.x); coordinates.put("y", node.y);
                __result.put("current_map_node", coordinates);
            }
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="getCombatState")
    public static class Counters {
        @SpirePostfixPatch
        @SuppressWarnings("unchecked")
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result) {
            HashMap<String, Object> counters = new HashMap<String, Object>();
            int attacks = 0, skills = 0;
            for (AbstractCard card : AbstractDungeon.actionManager.cardsPlayedThisTurn) {
                if (card.type == AbstractCard.CardType.ATTACK) attacks++;
                if (card.type == AbstractCard.CardType.SKILL) skills++;
            }
            counters.put("cards_played", AbstractDungeon.actionManager.cardsPlayedThisTurn.size());
            counters.put("attacks_played", attacks);
            counters.put("skills_played", skills);
            counters.put("attacks_this_combat", AbstractDungeon.actionManager.cardsPlayedThisCombat.stream()
                .filter(card -> card.type == AbstractCard.CardType.ATTACK).count());
            __result.put("turn_counters", counters);
            __result.put("energy_per_turn", AbstractDungeon.player.energy.energyMaster);
            __result.put("draw_per_turn", AbstractDungeon.player.gameHandSize);
            Object serialized = __result.get("monsters");
            if (serialized instanceof ArrayList) {
                ArrayList<Object> entries = (ArrayList<Object>) serialized;
                for (int i = 0; i < entries.size() && i < AbstractDungeon.getMonsters().monsters.size(); i++) {
                    if (!(entries.get(i) instanceof HashMap)) continue;
                    AbstractMonster monster = AbstractDungeon.getMonsters().monsters.get(i);
                    ((HashMap<String, Object>) entries.get(i)).put("entity_id", NativeIdentity.ledger.identify(monster));
                    ((HashMap<String, Object>) entries.get(i)).put("move_name", monster.moveName);
                    ((HashMap<String, Object>) entries.get(i)).put("native_mechanics", NativeMechanics.describe(monster, AbstractMonster.class));
                    ((HashMap<String,Object>) entries.get(i)).put("native_fields",nativeFields(monster,AbstractMonster.class));
                    ArrayList<Object> damageEntries=new ArrayList<Object>();
                    for (com.megacrit.cardcrawl.cards.DamageInfo damage:monster.damage) {
                        HashMap<String,Object> entry=new HashMap<String,Object>();
                        entry.put("base",damage.base);entry.put("adjusted",damage.output);
                        entry.put("type",damage.type.toString());damageEntries.add(entry);
                    }
                    HashMap<String,Object> damageCatalog=new HashMap<String,Object>();
                    damageCatalog.put("entries",damageEntries);
                    damageCatalog.put("scope","Loaded native damage entries, not a selected attack or predicted action outcome; current intent is separate.");
                    ((HashMap<String,Object>) entries.get(i)).put("damage_catalog",damageCatalog);
                }
            }
            __result.put("benchmark_normalized", benchmarkNormalized && AbstractDungeon.floorNum == 1);
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="convertCreaturePowersToJson",
                paramtypez={AbstractCreature.class})
    public static class Powers {
        @SpirePostfixPatch
        @SuppressWarnings("unchecked")
        public static ArrayList<Object> postfix(ArrayList<Object> __result, AbstractCreature creature) {
            for (Object entry : __result) {
                if (!(entry instanceof HashMap)) continue;
                HashMap<String, Object> state = (HashMap<String, Object>) entry;
                for (AbstractPower power : creature.powers) {
                    if (power.ID.equals(state.get("id"))) {
                        state.put("native_description", power.description);
                        state.put("native_mechanics", NativeMechanics.describe(power, AbstractPower.class));
                        state.put("native_fields", nativeFields(power, AbstractPower.class));
                        state.put("power_type", power.type.toString());
                        try {
                            state.put("is_turn_based", NativeFields.read(power, "isTurnBased"));
                        } catch (ReflectiveOperationException unavailable) {
                            state.put("turn_based_unknown", true);
                        }
                        break;
                    }
                }
            }
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="convertRelicToJson",
                paramtypez={AbstractRelic.class})
    public static class Relics {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result, AbstractRelic relic) {
            NativeCatalog.observe(relic);
            __result.put("native_description", relic.description);
            __result.put("native_mechanics", NativeMechanics.describe(relic, AbstractRelic.class));
            __result.put("native_fields", nativeFields(relic, AbstractRelic.class));
            __result.put("used_up", relic.usedUp);
            return __result;
        }
    }

    @SpirePatch(cls="communicationmod.GameStateConverter", method="convertPotionToJson",
                paramtypez={AbstractPotion.class})
    public static class Potions {
        @SpirePostfixPatch
        public static HashMap<String, Object> postfix(HashMap<String, Object> __result, AbstractPotion potion) {
            __result.put("native_description", potion.description);
            __result.put("native_mechanics", NativeMechanics.describe(potion, AbstractPotion.class));
            __result.put("native_fields", nativeFields(potion, AbstractPotion.class));
            __result.put("potency", potion.getPotency());
            return __result;
        }
    }
}
