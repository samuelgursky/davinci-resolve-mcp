// Structured stdin bridge used by the live Python server.
import { editSubtitleTimeline, inspectSubtitleTimeline, editCaptionTimeline, inspectCaptionTimeline, checkCaptionTimeline }
  from '../resolve-advanced/server/subtitle-timeline.mjs';
const operations = { inspect: inspectSubtitleTimeline, inspect_captions: inspectCaptionTimeline, write_captions: editCaptionTimeline,
  check_captions: checkCaptionTimeline };
try {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const { operation, ...request } = JSON.parse(input);
  process.stdout.write(JSON.stringify(await (operations[operation] || editSubtitleTimeline)(request)));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
