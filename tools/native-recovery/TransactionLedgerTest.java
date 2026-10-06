import jevstate.TransactionLedger;
import java.util.Map;

public class TransactionLedgerTest {
    static Map<?,?> receipt(TransactionLedger ledger) { return (Map<?,?>) ledger.snapshot().get("receipt"); }
    public static void main(String[] args) {
        TransactionLedger ledger = new TransactionLedger();
        assert ledger.begin(ledger.epoch,"one",0,"CHOOSE 0");
        ledger.accepted();
        assert !ledger.begin(ledger.epoch,"one",0,"CHOOSE 0");
        assert "accepted".equals(receipt(ledger).get("status"));
        ledger.decisionBoundary();
        assert "accepted".equals(receipt(ledger).get("status"));
        ledger.commandRegistered();ledger.decisionBoundary();
        assert "settled".equals(receipt(ledger).get("status"));
        assert !ledger.begin(ledger.epoch,"one",0,"CHOOSE 0");
        assert "settled".equals(receipt(ledger).get("status"));
        assert !ledger.begin(ledger.epoch,"one",2,"CHOOSE 1");
        assert "id_conflict".equals(receipt(ledger).get("error"));
        ledger.query("one");assert "CHOOSE 0".equals(receipt(ledger).get("command"));
        assert !ledger.begin(ledger.epoch,"stale",0,"END");
        assert "stale_revision".equals(receipt(ledger).get("error"));
        assert !ledger.begin("old-epoch","foreign",2,"END");
        assert "epoch_changed".equals(receipt(ledger).get("error"));
        assert ledger.begin(ledger.epoch,"active",2,"END");ledger.accepted();ledger.commandRegistered();
        for(int i=0;i<300;i++) assert !ledger.begin(ledger.epoch,"busy"+i,2,"END");
        ledger.query("active");assert "accepted".equals(receipt(ledger).get("status"));
        ledger.decisionBoundary();assert "settled".equals(receipt(ledger).get("status"));
        System.out.println("Native ledger invariants passed.");
    }
}
