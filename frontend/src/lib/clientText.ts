/** Older saved AI reports can still contain the bank's internal scoring metric. */
export function clientExplanation(text: string): string {
  return text
    .split(/(?<=[.!?])\s+|\n+/u)
    .filter((sentence) => !/(?:^|[^\p{L}])(?:балл(?:а|ов|ы|у|ам|ами|ах|е)?|risk[\s_-]*score)(?=$|[^\p{L}])/iu.test(sentence))
    .join(' ')
    .trim()
}
