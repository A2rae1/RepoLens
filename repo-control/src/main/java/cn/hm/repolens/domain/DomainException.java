package cn.hm.repolens.domain;

public class DomainException extends RuntimeException {
    private final int status;
    private final String code;
    public DomainException(int status, String code, String message) { super(message); this.status=status; this.code=code; }
    public int status() { return status; }
    public String code() { return code; }
    public static DomainException missing() { return new DomainException(404,"NOT_FOUND","资源不存在"); }
    public static DomainException conflict(String message) { return new DomainException(409,"STATE_CONFLICT",message); }
    public static DomainException forbidden() { return new DomainException(403,"FORBIDDEN","无此操作权限"); }
}
