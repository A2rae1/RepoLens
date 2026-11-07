package cn.hm.repolens.domain;
import java.time.LocalDateTime;
public final class Rows {
 private Rows(){}
 public record User(String id,String passwordHash,String role){}
 public record Outbox(String id,String topic,String aggregateId,String payload,String status,int attempts,LocalDateTime availableAt,LocalDateTime createdAt,String lastError,LocalDateTime leaseUntil,String leaseToken){}
}
