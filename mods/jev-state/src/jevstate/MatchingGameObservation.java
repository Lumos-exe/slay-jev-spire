package jevstate;

import basemod.BaseMod;
import basemod.interfaces.PostUpdateSubscriber;
import com.autoplay.gson.Gson;
import com.megacrit.cardcrawl.cards.AbstractCard;
import com.megacrit.cardcrawl.cards.CardGroup;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.events.shrines.GremlinMatchGame;
import communicationmod.ChoiceScreenUtils;
import communicationmod.patches.GremlinMatchGamePatch;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Adapter for a card-board UI, not a whitelist of card effects or identities.
 * Uses CommunicationMod's own revealed-card memory and native selectable order.
 */
public final class MatchingGameObservation implements PostUpdateSubscriber {
    private final Path output;
    private String previous;

    public MatchingGameObservation(String path) { output=Paths.get(path); }

    private static Map<String,Object> face(AbstractCard card) {
        Map<String,Object> result=new LinkedHashMap<String,Object>();
        result.put("id",card.cardID);result.put("uuid",card.uuid.toString());
        result.put("name",card.name);result.put("type",card.type.name());
        result.put("cost",card.cost);result.put("upgrades",card.timesUpgraded);
        result.put("raw_description",card.rawDescription);
        Map<String,Object> values=new LinkedHashMap<String,Object>();
        values.put("source","game_card_fields");values.put("scope","observed_event_card_face");
        values.put("damage",card.baseDamage);values.put("block",card.baseBlock);
        values.put("magic_number",card.baseMagicNumber);values.put("cost_for_turn",card.costForTurn);
        result.put("native_values",values);
        return result;
    }

    private static int slot(AbstractCard card) {
        Object value=GremlinMatchGamePatch.cardPositions.get(card.uuid);
        if (!(value instanceof Integer)) throw new IllegalStateException("Missing native card position");
        return (Integer)value;
    }

    private static Map<String,Object> card(AbstractCard card) {
        return VisibleCardSlot.describe(slot(card),card.uuid.toString(),
            GremlinMatchGamePatch.revealedCards.contains(card.uuid),!card.isFlipped,()->face(card));
    }

    public static Map<String,Object> capture() throws ReflectiveOperationException {
        if (AbstractDungeon.getCurrMapNode()==null || AbstractDungeon.getCurrRoom()==null
                || !(AbstractDungeon.getCurrRoom().event instanceof GremlinMatchGame)) return null;
        GremlinMatchGame event=(GremlinMatchGame)AbstractDungeon.getCurrRoom().event;
        String phase=((Enum<?>)NativeFields.read(event,"screen")).name();
        Map<String,Object> result=new LinkedHashMap<String,Object>();
        result.put("kind","matching_cards");result.put("phase",phase);
        result.put("attempts_remaining",NativeFields.read(event,"attemptCount"));
        result.put("pairs_matched",NativeFields.read(event,"cardsMatched"));
        result.put("native_event_text",Arrays.asList(GremlinMatchGame.DESCRIPTIONS));
        boolean play=phase.equals("PLAY");
        boolean ready=play ? !(Boolean)NativeFields.read(event,"gameDone")
            && ((Number)NativeFields.read(event,"waitTimer")).floatValue()<=0 : !phase.equals("CLEAN_UP");
        result.put("ready_for_choice",ready);
        result.put("visibility_scope","Card identities only appear if already revealed by the native UI. Stable slot numbers differ from current choice indices.");
        if (!play) return result;
        CardGroup group=(CardGroup)NativeFields.read(event,"cards");
        List<Object> board=new ArrayList<Object>(),choices=new ArrayList<Object>();
        for (AbstractCard card:group.group) board.add(card(card));
        int index=0;
        for (AbstractCard card:GremlinMatchGamePatch.getOrderedCards()) {
            Map<String,Object> choice=card(card);choice.put("choice_index",index++);
            choices.add(choice);
        }
        AbstractCard selected=(AbstractCard)NativeFields.read(event,"chosenCard");
        result.put("selected_slot",selected==null ? null : slot(selected));
        result.put("board",board);result.put("choices",choices);
        return result;
    }

    /** Hot recovery only. Future bridge versions embed capture() in the native
     * state directly; no already loaded classes are replaced by this observer.
     */
    public static void installSidecar(String path) {
        BaseMod.subscribe(new MatchingGameObservation(path));
    }

    @Override public void receivePostUpdate() {
        try {
            Map<String,Object> envelope=new LinkedHashMap<String,Object>();
            envelope.put("version",1);envelope.put("epoch",ActionProtocol.ledger.epoch);
            envelope.put("revision",ActionProtocol.ledger.currentRevision());
            Map<String,Object> view=capture();
            envelope.put("active",view!=null);
            if (view!=null) {
                envelope.put("run_id",NativeIdentity.ledger.runId());
                envelope.put("room_id",NativeIdentity.ledger.identify(AbstractDungeon.getCurrRoom()));
                envelope.put("event_id",GremlinMatchGame.ID);
                List<String> labels=new ArrayList<String>();
                for (String label:ChoiceScreenUtils.getEventScreenChoices()) labels.add(label.toLowerCase(Locale.ROOT));
                envelope.put("choice_labels",labels);envelope.put("view",view);
            }
            String json=new Gson().toJson(envelope);
            if (json.equals(previous)) return;
            Files.createDirectories(output.getParent());
            Path temporary=output.resolveSibling(output.getFileName()+".tmp");
            Files.write(temporary,json.getBytes(StandardCharsets.UTF_8));
            Files.move(temporary,output,StandardCopyOption.REPLACE_EXISTING);
            previous=json;
        } catch (Exception error) {
            System.err.println("Matching observation unavailable: "+error.getClass().getSimpleName());
        }
    }
}
