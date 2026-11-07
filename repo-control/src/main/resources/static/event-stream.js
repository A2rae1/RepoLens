/** Decode durable SSE frames independently of Vue and authentication state. */
export async function consumeEventStream(response, cursor, signal, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > 512_000) throw Error("事件内容超过上限");
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = frame.split(/\r?\n/);
        const seq = Number(
          lines.find((line) => line.startsWith("id:"))?.slice(3),
        );
        const kind = lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const payload = lines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (Number.isSafeInteger(seq) && seq > cursor && kind && payload) {
          const event = { seq, kind, data: JSON.parse(payload) };
          if (signal.aborted) return cursor;
          onEvent(event);
          cursor = seq;
        }
      }
    }
    return cursor;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
