import { test } from "node:test";
import assert from "node:assert/strict";
import { consumeEventStream } from "../src/main/resources/static/event-stream.js";

function response(chunks) {
  const encoder = new TextEncoder();
  return {
    body: new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
  };
}

test("split frames, CRLF, replayed sequences and heartbeat preserve exactly-once display", async () => {
  const seen = [];
  const cursor = await consumeEventStream(
    response([
      ": heartbeat\n\nid: 1\nevent: old\ndata: {}\n\n",
      'id: 2\r\nevent: result\r\ndata: {"message":',
      '"中文"}\r\n\r\nid: 2\nevent: duplicate\ndata: {}\n\n',
      "id: 3\nevent: done\ndata: {}\n\n",
    ]),
    1,
    new AbortController().signal,
    (event) => seen.push(event),
  );
  assert.equal(cursor, 3);
  assert.deepEqual(
    seen.map((event) => event.seq),
    [2, 3],
  );
  assert.equal(seen[0].data.message, "中文");
});

test("account/job cancellation stops delivery of later frames", async () => {
  const control = new AbortController();
  const seen = [];
  await consumeEventStream(
    response([
      "id: 1\nevent: first\ndata: {}\n\nid: 2\nevent: stale\ndata: {}\n\n",
    ]),
    0,
    control.signal,
    (event) => {
      seen.push(event);
      control.abort();
    },
  );
  assert.equal(seen.length, 1);
});

test("oversized unfinished frames cannot grow the client buffer indefinitely", async () => {
  await assert.rejects(
    () =>
      consumeEventStream(
        response(["x".repeat(512001)]),
        0,
        new AbortController().signal,
        () => {},
      ),
    /超过上限/,
  );
});
