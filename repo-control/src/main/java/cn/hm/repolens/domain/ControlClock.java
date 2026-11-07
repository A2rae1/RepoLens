package cn.hm.repolens.domain;
import java.time.*;
import java.util.UUID;
import org.springframework.stereotype.Component;
@Component
public class ControlClock {
 private final Clock clock;
 public ControlClock(Clock clock){this.clock=clock;}
 public LocalDateTime now(){return LocalDateTime.now(clock);}
 public static String id(){return UUID.randomUUID().toString();}
}
