import com.sun.tools.attach.VirtualMachine;
import com.sun.tools.attach.AgentLoadException;

public class AttachController {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("PID agent.jar report-path");
        VirtualMachine vm = VirtualMachine.attach(args[0]);
        try {
            try { vm.loadAgent(args[1], args[2]); }
            catch (AgentLoadException legacy) {
                // JDK 11 attaching to the bundled Java 8 can surface its
                // successful numeric acknowledgement as an exception.
                // The caller MUST still verify the in-game completion report.
                if (!"0".equals(legacy.getMessage())) throw legacy;
            }
        }
        finally { vm.detach(); }
        System.out.println("Agent attached; inspect the report for completion.");
    }
}
