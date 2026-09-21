import { Furigana, FuriganaExampleList } from './furigana'
import { useDialogModal } from './useDialogModal'

// One row per key in backend/app/grammar.py's _GRAMMAR_NOTES, so every
// grammar word or helper verb that can show up in a gloss popup has a home
// here too. Keep this list in sync if that dict changes.
//
// `kanjiTerm` is only set for helper verbs (居る, 仕舞う, ...): their kana
// phrase is what actually appears in text (見ている, not 見て居る), so the
// term is shown as hiragana with the kanji dictionary form in parentheses
// instead of the usual per-character furigana ruby. That pairing already
// gives its reading, so — unlike every other kanji in this file — the term
// and kanjiTerm columns are never additionally wrapped in furigana.
export type GrammarNote = {
  term: string
  kanjiTerm?: string
  description: string
  godan: ConjugationExample
  ichidan: ConjugationExample
  irregular: ConjugationExample
}

// The conjugated form shown in a cell, plus (when the form isn't just a
// cross-reference like "— (られる を使う)") a full example sentence and its
// translation, shown on hover. The irregular column's sentence always uses
// the する branch of the cell (勉強する), since a second sentence for 来る
// would double every row for little added benefit; 来る's own furigana
// still appears in the cell text since its reading shifts with conjugation
// (来[き]た, 来[く]る, 来[こ]ない) and can't be looked up mechanically.
export type ConjugationExample = {
  text: string
  sentence?: string
  translation?: string
}

const NA = '—'

// A grammar word with no verb-conjugation columns to show, either because it
// marks a noun rather than attaching to a verb, or because it attaches to
// something other than a verb stem (an adjective, or a noun it turns into a
// verb). Shown in its own section instead of a table with three empty cells.
export type GrammarSimpleNote = {
  term: string
  kanjiTerm?: string
  description: string
  examples: string[]
}

export const GRAMMAR_LEGEND: GrammarNote[] = [
  // Auxiliaries (助動詞)
  {
    term: 'た',
    description: 'past tense or completed action (たら: if/when)',
    godan: {
      text: '書[か]いた',
      sentence: '手紙[てがみ]を書[か]いた。',
      translation: 'I wrote a letter.',
    },
    ichidan: {
      text: '食[た]べた',
      sentence: 'ご飯[はん]を食[た]べた。',
      translation: 'I ate a meal.',
    },
    irregular: {
      text: 'した・来[き]た',
      sentence: '勉強[べんきょう]した。',
      translation: 'I studied.',
    },
  },
  {
    term: 'だ',
    description: 'copula: is (だろう: probably; なら: if; で: and/being)',
    godan: {
      text: '書[か]くだろう',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]くだろう。',
      translation: 'He will probably write a letter.',
    },
    ichidan: {
      text: '食[た]べるだろう',
      sentence: '彼[かれ]はご飯[はん]を食[た]べるだろう。',
      translation: 'He will probably eat.',
    },
    irregular: {
      text: 'するだろう・来[く]るだろう',
      sentence: '彼[かれ]は勉強[べんきょう]するだろう。',
      translation: 'He will probably study.',
    },
  },
  {
    term: 'です',
    description: 'polite copula: is (でしょう: probably)',
    godan: {
      text: '書[か]くでしょう',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]くでしょう。',
      translation: 'He will probably write a letter.',
    },
    ichidan: {
      text: '食[た]べるでしょう',
      sentence: '彼[かれ]はご飯[はん]を食[た]べるでしょう。',
      translation: 'He will probably eat.',
    },
    irregular: {
      text: 'するでしょう・来[く]るでしょう',
      sentence: '彼[かれ]は勉強[べんきょう]するでしょう。',
      translation: 'He will probably study.',
    },
  },
  {
    term: 'ます',
    description: 'polite verb ending',
    godan: {
      text: '書[か]きます',
      sentence: '手紙[てがみ]を書[か]きます。',
      translation: 'I write a letter.',
    },
    ichidan: {
      text: '食[た]べます',
      sentence: 'ご飯[はん]を食[た]べます。',
      translation: 'I eat a meal.',
    },
    irregular: {
      text: 'します・来[き]ます',
      sentence: '勉強[べんきょう]します。',
      translation: 'I study.',
    },
  },
  {
    term: 'ない',
    description: 'negation: not',
    godan: {
      text: '書[か]かない',
      sentence: '手紙[てがみ]を書[か]かない。',
      translation: "I won't write a letter.",
    },
    ichidan: {
      text: '食[た]べない',
      sentence: 'ご飯[はん]を食[た]べない。',
      translation: "I won't eat.",
    },
    irregular: {
      text: 'しない・来[こ]ない',
      sentence: '勉強[べんきょう]しない。',
      translation: "I won't study.",
    },
  },
  {
    term: 'ず',
    description: 'negation: not (ぬ/ん in speech)',
    godan: {
      text: '書[か]かず',
      sentence: '手紙[てがみ]を書[か]かずに出[で]かけた。',
      translation: 'I went out without writing the letter.',
    },
    ichidan: {
      text: '食[た]べず',
      sentence: 'ご飯[はん]を食[た]べずに寝[ね]た。',
      translation: 'I went to sleep without eating.',
    },
    irregular: {
      text: 'せず・来[こ]ず',
      sentence: '勉強[べんきょう]せずに遊[あそ]んだ。',
      translation: 'I played without studying.',
    },
  },
  {
    term: 'まい',
    description: "won't, or probably not",
    godan: {
      text: '書[か]くまい',
      sentence: 'もう手紙[てがみ]を書[か]くまい。',
      translation: "I won't write a letter anymore.",
    },
    ichidan: {
      text: '食[た]べまい・食[た]べるまい',
      sentence: 'もうご飯[はん]を食[た]べるまい。',
      translation: "I won't eat anymore.",
    },
    irregular: {
      text: 'するまい・来[こ]まい',
      sentence: 'もう勉強[べんきょう]するまい。',
      translation: "I won't study anymore.",
    },
  },
  {
    term: 'たい',
    description: 'want to',
    godan: {
      text: '書[か]きたい',
      sentence: '手紙[てがみ]を書[か]きたい。',
      translation: 'I want to write a letter.',
    },
    ichidan: {
      text: '食[た]べたい',
      sentence: 'ご飯[はん]を食[た]べたい。',
      translation: 'I want to eat.',
    },
    irregular: {
      text: 'したい・来[き]たい',
      sentence: '勉強[べんきょう]したい。',
      translation: 'I want to study.',
    },
  },
  {
    term: 'たがる',
    description: '(someone else) wants to',
    godan: {
      text: '書[か]きたがる',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]きたがる。',
      translation: 'He wants to write a letter.',
    },
    ichidan: {
      text: '食[た]べたがる',
      sentence: '彼[かれ]はご飯[はん]を食[た]べたがる。',
      translation: 'He wants to eat.',
    },
    irregular: {
      text: 'したがる・来[き]たがる',
      sentence: '彼[かれ]は勉強[べんきょう]したがる。',
      translation: 'He wants to study.',
    },
  },
  {
    term: 'れる',
    description: 'passive, can, or respectful form',
    godan: {
      text: '書[か]かれる',
      sentence: '先生[せんせい]は手紙[てがみ]を書[か]かれる。',
      translation: 'The teacher writes a letter. (respectful)',
    },
    ichidan: { text: `${NA} (られる を使う)` },
    irregular: { text: `${NA} (られる を使う)` },
  },
  {
    term: 'られる',
    description: 'passive, can, or respectful form',
    godan: { text: `${NA} (れる を使う)` },
    ichidan: {
      text: '食[た]べられる',
      sentence: '辛[から]い物[もの]が食[た]べられる。',
      translation: 'I can eat spicy food.',
    },
    irregular: {
      text: 'される・来[こ]られる',
      sentence: '掃除[そうじ]がされる。',
      translation: 'The cleaning gets done.',
    },
  },
  {
    term: 'せる',
    description: 'make or let (someone) do',
    godan: {
      text: '書[か]かせる',
      sentence: '先生[せんせい]は生徒[せいと]に手紙[てがみ]を書[か]かせる。',
      translation: 'The teacher makes the student write a letter.',
    },
    ichidan: { text: `${NA} (させる を使う)` },
    irregular: { text: `${NA} (させる を使う)` },
  },
  {
    term: 'させる',
    description: 'make or let (someone) do',
    godan: { text: `${NA} (せる を使う)` },
    ichidan: {
      text: '食[た]べさせる',
      sentence: '母[はは]は子供[こども]にご飯[はん]を食[た]べさせる。',
      translation: 'The mother makes her child eat.',
    },
    irregular: {
      text: 'させる・来[こ]させる',
      sentence: '先生[せんせい]は生徒[せいと]に勉強[べんきょう]させる。',
      translation: 'The teacher makes the student study.',
    },
  },
  {
    term: 'てる',
    description: 'short for ている: is doing, or the resulting state',
    godan: {
      text: '書[か]いてる',
      sentence: '今[いま]、手紙[てがみ]を書[か]いてる。',
      translation: "I'm writing a letter right now.",
    },
    ichidan: {
      text: '食[た]べてる',
      sentence: '今[いま]、ご飯[はん]を食[た]べてる。',
      translation: "I'm eating right now.",
    },
    irregular: {
      text: 'してる・来[き]てる',
      sentence: '今[いま]、勉強[べんきょう]してる。',
      translation: "I'm studying right now.",
    },
  },
  {
    term: 'ちゃう',
    description: 'short for てしまう: end up doing, or do completely',
    godan: {
      text: '書[か]いちゃう',
      sentence: '手紙[てがみ]を書[か]いちゃう。',
      translation: "I'll just go ahead and write the letter.",
    },
    ichidan: {
      text: '食[た]べちゃう',
      sentence: 'ご飯[はん]を食[た]べちゃう。',
      translation: "I'll just go ahead and eat.",
    },
    irregular: {
      text: 'しちゃう・来[き]ちゃう',
      sentence: '勉強[べんきょう]しちゃう。',
      translation: "I'll just go ahead and study.",
    },
  },
  {
    term: 'ちまう',
    description: 'short for てしまう: end up doing, or do completely',
    godan: {
      text: '書[か]いちまう',
      sentence: '手紙[てがみ]を書[か]いちまう。',
      translation: "I'll just write the darn letter.",
    },
    ichidan: {
      text: '食[た]べちまう',
      sentence: 'ご飯[はん]を食[た]べちまう。',
      translation: "I'll just eat the darn thing.",
    },
    irregular: {
      text: 'しちまう・来[き]ちまう',
      sentence: '勉強[べんきょう]しちまう。',
      translation: "I'll just study already.",
    },
  },
  {
    term: 'とく',
    description: 'short for ておく: do in advance, or leave as is',
    godan: {
      text: '書[か]いとく',
      sentence: '手紙[てがみ]を書[か]いとく。',
      translation: "I'll write the letter in advance.",
    },
    ichidan: {
      text: '食[た]べとく',
      sentence: 'ご飯[はん]を食[た]べとく。',
      translation: "I'll eat now, just in case.",
    },
    irregular: {
      text: 'しとく・来[き]とく',
      sentence: '勉強[べんきょう]しとく。',
      translation: "I'll study in advance.",
    },
  },
  {
    term: 'てく',
    description: 'short for ていく: go on doing from now',
    godan: {
      text: '書[か]いてく',
      sentence: '手紙[てがみ]を書[か]いてく。',
      translation: "I'm going to go write a letter.",
    },
    ichidan: {
      text: '食[た]べてく',
      sentence: 'ご飯[はん]を食[た]べてく。',
      translation: "I'll eat before I go.",
    },
    irregular: {
      text: 'してく・来[き]てく',
      sentence: '勉強[べんきょう]してく。',
      translation: "I'll study and then go.",
    },
  },
  {
    term: 'らしい',
    description: 'seems, apparently',
    godan: {
      text: '書[か]くらしい',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]くらしい。',
      translation: 'Apparently he writes letters.',
    },
    ichidan: {
      text: '食[た]べるらしい',
      sentence: '彼[かれ]はご飯[はん]を食[た]べるらしい。',
      translation: 'Apparently he eats a lot.',
    },
    irregular: {
      text: 'するらしい・来[く]るらしい',
      sentence: '彼[かれ]は勉強[べんきょう]するらしい。',
      translation: 'Apparently he studies.',
    },
  },
  {
    term: 'べし',
    description: 'should, ought to',
    godan: {
      text: '書[か]くべし',
      sentence: '手紙[てがみ]は自分[じぶん]で書[か]くべし。',
      translation: 'You should write the letter yourself.',
    },
    ichidan: {
      text: '食[た]べるべし',
      sentence: '野菜[やさい]は毎日[まいにち]食[た]べるべし。',
      translation: 'You should eat vegetables every day.',
    },
    irregular: {
      text: 'するべし・来[く]るべし',
      sentence: '勉強[べんきょう]はするべし。',
      translation: 'You should study.',
    },
  },
  {
    term: 'やがる',
    description: '(contemptuous) has the nerve to',
    godan: {
      text: '書[か]きやがる',
      sentence: 'あいつ、また手紙[てがみ]を書[か]きやがる。',
      translation: 'That jerk is writing a letter again.',
    },
    ichidan: {
      text: '食[た]べやがる',
      sentence: 'あいつ、また食[た]べやがる。',
      translation: 'That jerk is eating again.',
    },
    irregular: {
      text: 'しやがる・来[き]やがる',
      sentence: 'あいつ、また来[き]やがる。',
      translation: 'That jerk has the nerve to come again.',
    },
  },
  // Stems of そうだ/ようだ/みたいだ (形状詞-助動詞語幹)
  {
    term: 'そう',
    description: 'looks like, or I hear that (after a plain form)',
    godan: {
      text: '書[か]きそう',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]きそう。',
      translation: "He looks like he's about to write a letter.",
    },
    ichidan: {
      text: '食[た]べそう',
      sentence: '彼[かれ]はご飯[はん]を食[た]べそう。',
      translation: "He looks like he's about to eat.",
    },
    irregular: {
      text: 'しそう・来[き]そう',
      sentence: '彼[かれ]は勉強[べんきょう]しそう。',
      translation: "He looks like he's about to study.",
    },
  },
  {
    term: 'よう',
    description: 'seems, or like',
    godan: {
      text: '書[か]くよう(だ)',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]くようだ。',
      translation: 'It seems he writes letters.',
    },
    ichidan: {
      text: '食[た]べるよう(だ)',
      sentence: '彼[かれ]はご飯[はん]を食[た]べるようだ。',
      translation: 'It seems he eats a lot.',
    },
    irregular: {
      text: 'するよう(だ)・来[く]るよう(だ)',
      sentence: '彼[かれ]は勉強[べんきょう]するようだ。',
      translation: 'It seems he studies.',
    },
  },
  {
    term: 'みたい',
    description: 'seems, or like (casual)',
    godan: {
      text: '書[か]くみたい',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]くみたい。',
      translation: 'Looks like he writes letters.',
    },
    ichidan: {
      text: '食[た]べるみたい',
      sentence: '彼[かれ]はご飯[はん]を食[た]べるみたい。',
      translation: 'Looks like he eats a lot.',
    },
    irregular: {
      text: 'するみたい・来[く]るみたい',
      sentence: '彼[かれ]は勉強[べんきょう]するみたい。',
      translation: 'Looks like he studies.',
    },
  },
  // Particles (助詞)
  {
    term: 'て',
    description: 'and, then; links to what follows (ちゃ: short for ては)',
    godan: {
      text: '書[か]いて',
      sentence: '手紙[てがみ]を書[か]いて、出[だ]した。',
      translation: 'I wrote the letter and sent it.',
    },
    ichidan: {
      text: '食[た]べて',
      sentence: 'ご飯[はん]を食[た]べて、寝[ね]た。',
      translation: 'I ate and went to sleep.',
    },
    irregular: {
      text: 'して・来[き]て',
      sentence: '勉強[べんきょう]して、寝[ね]た。',
      translation: 'I studied and went to sleep.',
    },
  },
  {
    term: 'で',
    description: 'and, then; links to what follows',
    godan: {
      text: '読[よ]んで',
      sentence: '本[ほん]を読[よ]んで、感動[かんどう]した。',
      translation: 'I read the book and was moved.',
    },
    ichidan: { text: `${NA} (常に て)` },
    irregular: { text: `${NA} (常に て)` },
  },
  {
    term: 'ば',
    description: 'if',
    godan: {
      text: '書[か]けば',
      sentence: '手紙[てがみ]を書[か]けば、気持[きも]ちが伝[つた]わる。',
      translation: 'If you write a letter, your feelings will get across.',
    },
    ichidan: {
      text: '食[た]べれば',
      sentence: '野菜[やさい]を食[た]べれば、元気[げんき]になる。',
      translation: "If you eat vegetables, you'll feel better.",
    },
    irregular: {
      text: 'すれば・来[く]れば',
      sentence: '勉強[べんきょう]すれば、テストに受[う]かる。',
      translation: "If you study, you'll pass the test.",
    },
  },
  {
    term: 'たら',
    description: 'if, when',
    godan: {
      text: '書[か]いたら',
      sentence: '手紙[てがみ]を書[か]いたら、送[おく]ってね。',
      translation: "When you've written the letter, please send it.",
    },
    ichidan: {
      text: '食[た]べたら',
      sentence: 'ご飯[はん]を食[た]べたら、歯[は]を磨[みが]いて。',
      translation: "When you've finished eating, brush your teeth.",
    },
    irregular: {
      text: 'したら・来[き]たら',
      sentence: '勉強[べんきょう]したら、休[やす]んでいいよ。',
      translation: "Once you've studied, you can rest.",
    },
  },
  {
    term: 'ても',
    description: 'even if',
    godan: {
      text: '書[か]いても',
      sentence: '手紙[てがみ]を書[か]いても、返事[へんじ]が来[こ]ない。',
      translation: 'Even if I write a letter, no reply comes.',
    },
    ichidan: {
      text: '食[た]べても',
      sentence: 'たくさん食[た]べても、太[ふと]らない。',
      translation: "Even if I eat a lot, I don't gain weight.",
    },
    irregular: {
      text: 'しても・来[き]ても',
      sentence: '勉強[べんきょう]しても、わからない。',
      translation: "Even if I study, I don't understand it.",
    },
  },
  {
    term: 'けれど',
    description: 'but, although',
    godan: {
      text: '書[か]くけれど',
      sentence: '手紙[てがみ]を書[か]くけれど、まだ出[だ]していない。',
      translation: "I'm writing a letter, but I haven't sent it yet.",
    },
    ichidan: {
      text: '食[た]べるけれど',
      sentence:
        'ご飯[はん]を食[た]べるけれど、お腹[なか]がまだ空[す]いている。',
      translation: "I'm eating, but I'm still hungry.",
    },
    irregular: {
      text: 'するけれど・来[く]るけれど',
      sentence: '勉強[べんきょう]するけれど、集中[しゅうちゅう]できない。',
      translation: "I study, but I can't concentrate.",
    },
  },
  {
    term: 'から',
    description: 'because, or from',
    godan: {
      text: '書[か]くから',
      sentence: '手紙[てがみ]を書[か]くから、待[ま]ってて。',
      translation: "I'll write the letter, so wait for me.",
    },
    ichidan: {
      text: '食[た]べるから',
      sentence: 'ご飯[はん]を食[た]べるから、座[すわ]って。',
      translation: "I'm going to eat, so sit down.",
    },
    irregular: {
      text: 'するから・来[く]るから',
      sentence: '勉強[べんきょう]するから、静[しず]かにして。',
      translation: "I'm going to study, so be quiet.",
    },
  },
  {
    term: 'ので',
    description: 'because',
    godan: {
      text: '書[か]くので',
      sentence: '手紙[てがみ]を書[か]くので、静[しず]かにしてください。',
      translation: "I'm writing a letter, so please be quiet.",
    },
    ichidan: {
      text: '食[た]べるので',
      sentence: 'ご飯[はん]を食[た]べるので、後[あと]で電話[でんわ]します。',
      translation: "I'm going to eat, so I'll call you later.",
    },
    irregular: {
      text: 'するので・来[く]るので',
      sentence: '勉強[べんきょう]するので、部屋[へや]を借[か]りる。',
      translation: "Since I'm going to study, I'll rent a room.",
    },
  },
  {
    term: 'のに',
    description: 'although, even though',
    godan: {
      text: '書[か]くのに',
      sentence: '手紙[てがみ]を書[か]くのに、ペンを忘[わす]れた。',
      translation:
        'Even though I was about to write a letter, I forgot my pen.',
    },
    ichidan: {
      text: '食[た]べるのに',
      sentence: 'ご飯[はん]を食[た]べるのに、箸[はし]がない。',
      translation: "Even though I'm about to eat, there are no chopsticks.",
    },
    irregular: {
      text: 'するのに・来[く]るのに',
      sentence: '勉強[べんきょう]するのに、集中力[しゅうちゅうりょく]がいる。',
      translation: 'It takes concentration to study.',
    },
  },
  {
    term: 'し',
    description: 'and also (listing reasons)',
    godan: {
      text: '書[か]くし',
      sentence: '手紙[てがみ]も書[か]くし、電話[でんわ]もする。',
      translation: "I'll write a letter, and I'll also call.",
    },
    ichidan: {
      text: '食[た]べるし',
      sentence: 'ご飯[はん]も食[た]べるし、お菓子[かし]も食[た]べる。',
      translation: "I'll eat a meal, and I'll also eat sweets.",
    },
    irregular: {
      text: 'するし・来[く]るし',
      sentence: '勉強[べんきょう]もするし、運動[うんどう]もする。',
      translation: 'I study, and I also exercise.',
    },
  },
  {
    term: 'たり',
    description: 'doing things like (listing actions)',
    godan: {
      text: '書[か]いたり',
      sentence: '手紙[てがみ]を書[か]いたり、本[ほん]を読[よ]んだりする。',
      translation: 'I do things like writing letters and reading books.',
    },
    ichidan: {
      text: '食[た]べたり',
      sentence: 'ご飯[はん]を食[た]べたり、寝[ね]たりする。',
      translation: 'I do things like eating and sleeping.',
    },
    irregular: {
      text: 'したり・来[き]たり',
      sentence: '勉強[べんきょう]したり、遊[あそ]んだりする。',
      translation: 'I do things like studying and playing.',
    },
  },
  {
    term: 'ながら',
    description: 'while',
    godan: {
      text: '書[か]きながら',
      sentence: '音楽[おんがく]を聞[き]きながら、手紙[てがみ]を書[か]く。',
      translation: 'I write a letter while listening to music.',
    },
    ichidan: {
      text: '食[た]べながら',
      sentence: 'テレビを見[み]ながら、ご飯[はん]を食[た]べる。',
      translation: 'I eat while watching TV.',
    },
    irregular: {
      text: 'しながら・来[き]ながら',
      sentence: '音楽[おんがく]を聞[き]きながら、勉強[べんきょう]する。',
      translation: 'I study while listening to music.',
    },
  },
  {
    term: 'の',
    description: "of, 's; or makes a clause a noun (のだ/んだ explains)",
    godan: {
      text: '書[か]くの',
      sentence: '手紙[てがみ]を書[か]くのが好[す]きだ。',
      translation: 'I like writing letters.',
    },
    ichidan: {
      text: '食[た]べるの',
      sentence: 'ご飯[はん]を食[た]べるのが好[す]きだ。',
      translation: 'I like eating.',
    },
    irregular: {
      text: 'するの・来[く]るの',
      sentence: '勉強[べんきょう]するのが好[す]きだ。',
      translation: 'I like studying.',
    },
  },
  {
    term: 'って',
    description: 'quoting: says that, or I hear that',
    godan: {
      text: '書[か]くって',
      sentence: '彼[かれ]は手紙[てがみ]を書[か]くって言[い]ってた。',
      translation: "He said he'd write a letter.",
    },
    ichidan: {
      text: '食[た]べるって',
      sentence: '彼[かれ]はご飯[はん]を食[た]べるって言[い]ってた。',
      translation: "He said he'd eat.",
    },
    irregular: {
      text: 'するって・来[く]るって',
      sentence: '彼[かれ]は勉強[べんきょう]するって言[い]ってた。',
      translation: "He said he'd study.",
    },
  },
  {
    term: 'と',
    description: 'and, with; quoting: that; or when, if',
    godan: {
      text: '書[か]くと',
      sentence: '手紙[てがみ]を書[か]くと、気持[きも]ちが落[お]ち着[つ]く。',
      translation: 'When I write a letter, I feel calm.',
    },
    ichidan: {
      text: '食[た]べると',
      sentence: '野菜[やさい]を食[た]べると、元気[げんき]になる。',
      translation: 'When I eat vegetables, I feel better.',
    },
    irregular: {
      text: 'すると・来[く]ると',
      sentence: '勉強[べんきょう]すると、眠[ねむ]くなる。',
      translation: 'When I study, I get sleepy.',
    },
  },
  {
    term: 'ばかり',
    description: 'only, or just did',
    godan: {
      text: '書[か]いたばかり',
      sentence: '手紙[てがみ]を書[か]いたばかりだ。',
      translation: 'I just wrote a letter.',
    },
    ichidan: {
      text: '食[た]べたばかり',
      sentence: 'ご飯[はん]を食[た]べたばかりだ。',
      translation: 'I just ate.',
    },
    irregular: {
      text: 'したばかり・来[き]たばかり',
      sentence: '勉強[べんきょう]したばかりだ。',
      translation: 'I just studied.',
    },
  },
  {
    term: 'よ',
    description: 'sentence-final: asserts or informs',
    godan: {
      text: '書[か]くよ',
      sentence: '手紙[てがみ]を書[か]くよ。',
      translation: "I'll write the letter, you know.",
    },
    ichidan: {
      text: '食[た]べるよ',
      sentence: 'ご飯[はん]を食[た]べるよ。',
      translation: "I'll eat, you know.",
    },
    irregular: {
      text: 'するよ・来[く]るよ',
      sentence: '勉強[べんきょう]するよ。',
      translation: "I'll study, you know.",
    },
  },
  {
    term: 'ね',
    description: 'sentence-final: seeks agreement, softens',
    godan: {
      text: '書[か]くね',
      sentence: '手紙[てがみ]を書[か]くね。',
      translation: "I'll write the letter, okay?",
    },
    ichidan: {
      text: '食[た]べるね',
      sentence: 'ご飯[はん]を食[た]べるね。',
      translation: "I'll eat, okay?",
    },
    irregular: {
      text: 'するね・来[く]るね',
      sentence: '勉強[べんきょう]するね。',
      translation: "I'll study, okay?",
    },
  },
  {
    term: 'な',
    description: "sentence-final: don't (after a plain verb), or musing",
    godan: {
      text: '書[か]くな',
      sentence: 'この紙[かみ]に何[なに]も書[か]くな。',
      translation: "Don't write anything on this paper.",
    },
    ichidan: {
      text: '食[た]べるな',
      sentence: 'それを食[た]べるな。',
      translation: "Don't eat that.",
    },
    irregular: {
      text: 'するな・来[く]るな',
      sentence: '心配[しんぱい]するな。',
      translation: "Don't worry.",
    },
  },
  {
    term: 'か',
    description: 'question marker, or',
    godan: {
      text: '書[か]くか',
      sentence: '手紙[てがみ]を書[か]くか？',
      translation: 'Will you write a letter?',
    },
    ichidan: {
      text: '食[た]べるか',
      sentence: 'ご飯[はん]を食[た]べるか？',
      translation: 'Will you eat?',
    },
    irregular: {
      text: 'するか・来[く]るか',
      sentence: '勉強[べんきょう]するか？',
      translation: 'Will you study?',
    },
  },
  {
    term: 'わ',
    description: 'sentence-final: soft emphasis',
    godan: {
      text: '書[か]くわ',
      sentence: '私[わたし]が手紙[てがみ]を書[か]くわ。',
      translation: "I'll write the letter.",
    },
    ichidan: {
      text: '食[た]べるわ',
      sentence: '私[わたし]がご飯[はん]を食[た]べるわ。',
      translation: "I'll eat.",
    },
    irregular: {
      text: 'するわ・来[く]るわ',
      sentence: '私[わたし]が勉強[べんきょう]するわ。',
      translation: "I'll study.",
    },
  },
  {
    term: 'ぞ',
    description: 'sentence-final: strong emphasis',
    godan: {
      text: '書[か]くぞ',
      sentence: '手紙[てがみ]を書[か]くぞ。',
      translation: "I'm gonna write this letter!",
    },
    ichidan: {
      text: '食[た]べるぞ',
      sentence: 'ご飯[はん]を食[た]べるぞ。',
      translation: "I'm gonna eat!",
    },
    irregular: {
      text: 'するぞ・来[く]るぞ',
      sentence: '勉強[べんきょう]するぞ。',
      translation: "I'm gonna study!",
    },
  },
  {
    term: 'ぜ',
    description: 'sentence-final: casual emphasis',
    godan: {
      text: '書[か]くぜ',
      sentence: '手紙[てがみ]を書[か]くぜ。',
      translation: "I'll write the letter, alright.",
    },
    ichidan: {
      text: '食[た]べるぜ',
      sentence: 'ご飯[はん]を食[た]べるぜ。',
      translation: "I'll eat, alright.",
    },
    irregular: {
      text: 'するぜ・来[く]るぜ',
      sentence: '勉強[べんきょう]するぜ。',
      translation: "I'll study, alright.",
    },
  },
  {
    term: 'さ',
    description: 'sentence-final: casual assertion',
    godan: {
      text: '書[か]くさ',
      sentence: '手紙[てがみ]くらい書[か]くさ。',
      translation: "Of course I'll write a letter.",
    },
    ichidan: {
      text: '食[た]べるさ',
      sentence: 'ご飯[はん]くらい食[た]べるさ。',
      translation: "Of course I'll eat.",
    },
    irregular: {
      text: 'するさ・来[く]るさ',
      sentence: '勉強[べんきょう]くらいするさ。',
      translation: "Of course I'll study.",
    },
  },
  {
    term: 'じゃん',
    description: "casual: isn't it, you know",
    godan: {
      text: '書[か]くじゃん',
      sentence: '手紙[てがみ]、書[か]くじゃん。',
      translation: "You're writing a letter, aren't you.",
    },
    ichidan: {
      text: '食[た]べるじゃん',
      sentence: 'ご飯[はん]、食[た]べるじゃん。',
      translation: "You're eating, aren't you.",
    },
    irregular: {
      text: 'するじゃん・来[く]るじゃん',
      sentence: '勉強[べんきょう]するじゃん。',
      translation: "You're studying, aren't you.",
    },
  },
  // Helper verbs and adjectives (補助動詞/補助形容詞)
  {
    term: 'ている',
    kanjiTerm: '居る',
    description: 'is doing, or the resulting state',
    godan: {
      text: '書[か]いている',
      sentence: '今[いま]、手紙[てがみ]を書[か]いている。',
      translation: 'I am writing a letter right now.',
    },
    ichidan: {
      text: '食[た]べている',
      sentence: '今[いま]、ご飯[はん]を食[た]べている。',
      translation: 'I am eating right now.',
    },
    irregular: {
      text: 'している・来[き]ている',
      sentence: '今[いま]、勉強[べんきょう]している。',
      translation: 'I am studying right now.',
    },
  },
  {
    term: 'てある',
    kanjiTerm: '有る',
    description: 'has been done and left that way',
    godan: {
      text: '書[か]いてある',
      sentence: '壁[かべ]に手紙[てがみ]が書[か]いてある。',
      translation: 'A letter is written on the wall.',
    },
    ichidan: {
      text: '食[た]べてある',
      sentence: 'もう朝[あさ]ご飯[はん]は食[た]べてある。',
      translation: 'Breakfast has already been eaten and taken care of.',
    },
    irregular: {
      text: 'してある・来[き]てある',
      sentence: '準備[じゅんび]はしてある。',
      translation: 'The preparations have been made and left ready.',
    },
  },
  {
    term: 'てしまう',
    kanjiTerm: '仕舞う',
    description: 'end up doing, or do completely',
    godan: {
      text: '書[か]いてしまう',
      sentence: '秘密[ひみつ]を手紙[てがみ]に書[か]いてしまう。',
      translation: 'I end up writing the secret in the letter.',
    },
    ichidan: {
      text: '食[た]べてしまう',
      sentence: 'ケーキを全部[ぜんぶ]食[た]べてしまう。',
      translation: 'I end up eating the whole cake.',
    },
    irregular: {
      text: 'してしまう・来[き]てしまう',
      sentence: 'つい夜[よ]更[ふ]かししてしまう。',
      translation: 'I end up staying up late.',
    },
  },
  {
    term: 'てみる',
    kanjiTerm: '見る',
    description: 'try doing',
    godan: {
      text: '書[か]いてみる',
      sentence: '手紙[てがみ]を書[か]いてみる。',
      translation: "I'll try writing a letter.",
    },
    ichidan: {
      text: '食[た]べてみる',
      sentence: 'この料理[りょうり]を食[た]べてみる。',
      translation: "I'll try eating this dish.",
    },
    irregular: {
      text: 'してみる・来[き]てみる',
      sentence: '新[あたら]しいことを勉強[べんきょう]してみる。',
      translation: "I'll try studying something new.",
    },
  },
  {
    term: 'ておく',
    description: 'do in advance, or leave as is',
    godan: {
      text: '書[か]いておく',
      sentence: '手紙[てがみ]を書[か]いておく。',
      translation: "I'll write the letter in advance.",
    },
    ichidan: {
      text: '食[た]べておく',
      sentence: '朝[あさ]ご飯[はん]を食[た]べておく。',
      translation: "I'll eat breakfast now, just in case.",
    },
    irregular: {
      text: 'しておく・来[き]ておく',
      sentence: '予習[よしゅう]をしておく。',
      translation: "I'll do the preview studying in advance.",
    },
  },
  // _GRAMMAR_NOTES has both おく (kana) and 置く (kanji) as separate keys for
  // this same ておく, since either spelling shows up in real text — this
  // second row is intentionally a near-duplicate of the one above it, not a
  // copy-paste mistake.
  {
    term: 'ておく',
    kanjiTerm: '置く',
    description: 'do in advance, or leave as is',
    godan: {
      text: '書[か]いておく',
      sentence: '手紙[てがみ]を書[か]いておく。',
      translation: "I'll write the letter in advance.",
    },
    ichidan: {
      text: '食[た]べておく',
      sentence: '朝[あさ]ご飯[はん]を食[た]べておく。',
      translation: "I'll eat breakfast now, just in case.",
    },
    irregular: {
      text: 'しておく・来[き]ておく',
      sentence: '予習[よしゅう]をしておく。',
      translation: "I'll do the preview studying in advance.",
    },
  },
  {
    term: 'ていく',
    kanjiTerm: '行く',
    description: 'go on doing from now',
    godan: {
      text: '書[か]いていく',
      sentence: 'レポートを書[か]いていく。',
      translation: "I'll go on writing the report from here.",
    },
    ichidan: {
      text: '食[た]べていく',
      sentence: '朝[あさ]ご飯[はん]を食[た]べていく。',
      translation: "I'll eat breakfast before I go.",
    },
    irregular: {
      text: 'していく・来[き]ていく',
      sentence: '毎日[まいにち]勉強[べんきょう]していく。',
      translation: "I'll keep studying every day, from now on.",
    },
  },
  {
    term: 'てくる',
    kanjiTerm: '来る',
    description: 'has been doing up to now, or go and do',
    godan: {
      text: '書[か]いてくる',
      sentence: '手紙[てがみ]を書[か]いてくる。',
      translation: "I'll go write a letter and come back.",
    },
    ichidan: {
      text: '食[た]べてくる',
      sentence: '先[さき]にご飯[はん]を食[た]べてくる。',
      translation: "I'll go eat first and come back.",
    },
    irregular: {
      text: 'してくる・来[き]てくる',
      sentence: '買[か]い物[もの]してくる。',
      translation: "I'll go shopping and come back.",
    },
  },
  {
    term: 'てもらう',
    kanjiTerm: '貰う',
    description: 'have (someone) do for you',
    godan: {
      text: '書[か]いてもらう',
      sentence: '友達[ともだち]に手紙[てがみ]を書[か]いてもらう。',
      translation: 'I have my friend write the letter for me.',
    },
    ichidan: {
      text: '食[た]べてもらう',
      sentence: '子供[こども]にご飯[はん]を食[た]べてもらう。',
      translation: 'I have my child eat the meal.',
    },
    irregular: {
      text: 'してもらう・来[き]てもらう',
      sentence: '先生[せんせい]に説明[せつめい]してもらう。',
      translation: 'I have the teacher explain it to me.',
    },
  },
  {
    term: 'てくれる',
    kanjiTerm: '呉れる',
    description: '(someone) does for you',
    godan: {
      text: '書[か]いてくれる',
      sentence: '友達[ともだち]が手紙[てがみ]を書[か]いてくれる。',
      translation: 'My friend writes the letter for me.',
    },
    ichidan: {
      text: '食[た]べてくれる',
      sentence: '子供[こども]がご飯[はん]を食[た]べてくれる。',
      translation: 'My child eats the meal for me.',
    },
    irregular: {
      text: 'してくれる・来[き]てくれる',
      sentence: '先生[せんせい]が説明[せつめい]してくれる。',
      translation: 'The teacher explains it for me.',
    },
  },
  {
    term: 'てあげる',
    kanjiTerm: '上げる',
    description: 'do for (someone)',
    godan: {
      text: '書[か]いてあげる',
      sentence: '友達[ともだち]に手紙[てがみ]を書[か]いてあげる。',
      translation: "I'll write the letter for my friend.",
    },
    ichidan: {
      text: '食[た]べてあげる',
      sentence: '残[のこ]りを食[た]べてあげる。',
      translation: "I'll eat the rest for you.",
    },
    irregular: {
      text: 'してあげる・来[き]てあげる',
      sentence: '手伝[てつだ]いをしてあげる。',
      translation: "I'll help out for you.",
    },
  },
  {
    term: 'てやる',
    kanjiTerm: '遣る',
    description: 'do for (someone), or do defiantly',
    godan: {
      text: '書[か]いてやる',
      sentence: '弟[おとうと]に手紙[てがみ]を書[か]いてやる。',
      translation: "I'll write the letter for my little brother.",
    },
    ichidan: {
      text: '食[た]べてやる',
      sentence: '残[のこ]り物[もの]を食[た]べてやる。',
      translation: "I'll eat the leftovers, just to help.",
    },
    irregular: {
      text: 'してやる・来[き]てやる',
      sentence: '勉強[べんきょう]してやる。',
      translation: "I'll study, just to show them.",
    },
  },
  {
    term: 'てみせる',
    kanjiTerm: '見せる',
    description: 'show you can, or will definitely do',
    godan: {
      text: '書[か]いてみせる',
      sentence: '手紙[てがみ]を書[か]いてみせる。',
      translation: "I'll show you I can write the letter.",
    },
    ichidan: {
      text: '食[た]べてみせる',
      sentence: '全部[ぜんぶ]食[た]べてみせる。',
      translation: "I'll show you I can eat it all.",
    },
    irregular: {
      text: 'してみせる・来[き]てみせる',
      sentence: 'きっと合格[ごうかく]してみせる。',
      translation: "I'll show you I can pass, for sure.",
    },
  },
  {
    term: 'て回る',
    kanjiTerm: '回る',
    description: 'go around doing',
    godan: {
      text: '書[か]いて回[まわ]る',
      sentence: 'みんなにメッセージを書[か]いて回[まわ]る。',
      translation: 'I go around writing messages to everyone.',
    },
    ichidan: {
      text: '食[た]べて回[まわ]る',
      sentence: '屋台[やたい]の料理[りょうり]を食[た]べて回[まわ]る。',
      translation: 'I go around eating food from the stalls.',
    },
    irregular: {
      text: 'して回[まわ]る・来[き]て回[まわ]る',
      sentence: '挨拶[あいさつ]して回[まわ]る。',
      translation: 'I go around greeting everyone.',
    },
  },
  {
    term: 'てほしい',
    kanjiTerm: '欲しい',
    description: 'want (someone) to do',
    godan: {
      text: '書[か]いてほしい',
      sentence: '手紙[てがみ]を書[か]いてほしい。',
      translation: 'I want you to write the letter.',
    },
    ichidan: {
      text: '食[た]べてほしい',
      sentence: 'ご飯[はん]を食[た]べてほしい。',
      translation: 'I want you to eat.',
    },
    irregular: {
      text: 'してほしい・来[き]てほしい',
      sentence: '勉強[べんきょう]してほしい。',
      translation: 'I want you to study.',
    },
  },
]

// Case and binding particles: they mark a noun's role in the sentence and
// don't attach after a verb stem, so there's no godan/ichidan/irregular form
// to compare. Examples are shown inline rather than on hover.
export const GRAMMAR_NOUN_PARTICLES: GrammarSimpleNote[] = [
  {
    term: 'に',
    description: 'to, at, in, for',
    examples: [
      '学校[がっこう]に行[い]く (go to school)',
      '七時[しちじ]に起[お]きる (get up at 7:00)',
    ],
  },
  {
    term: 'を',
    description: 'object marker',
    examples: ['パンを食[た]べる (eat bread)'],
  },
  {
    term: 'が',
    description: 'subject marker, or but',
    examples: ['猫[ねこ]が好[す]きだ (I like cats)'],
  },
  {
    term: 'は',
    description: 'topic marker, or contrast',
    examples: ['私[わたし]は学生[がくせい]だ (I am a student)'],
  },
  {
    term: 'も',
    description: 'also, even',
    examples: ['私[わたし]も行[い]く (I will go too)'],
  },
  {
    term: 'へ',
    description: 'toward, to',
    examples: ['東京[とうきょう]へ行[い]く (go to Tokyo)'],
  },
  {
    term: 'や',
    description: 'and (among others)',
    examples: ['りんごやみかん (apples and oranges, among others)'],
  },
  {
    term: 'より',
    description: 'than, from',
    examples: ['彼[かれ]より速[はや]い (faster than him)'],
  },
  {
    term: 'まで',
    description: 'until, even',
    examples: ['駅[えき]まで歩[ある]く (walk to the station)'],
  },
  {
    term: 'ほど',
    description: 'to the extent that',
    examples: ['彼[かれ]ほど上手[じょうず]じゃない (not as skilled as him)'],
  },
  {
    term: 'くらい',
    description: 'about, to the degree that',
    examples: ['一時間[いちじかん]くらい待[ま]った (waited about an hour)'],
  },
  {
    term: 'だけ',
    description: 'only',
    examples: ['少[すこ]しだけ食[た]べた (ate just a little)'],
  },
  {
    term: 'しか',
    description: 'nothing but (with a negative)',
    examples: ['一[ひと]つしかない (there is only one)'],
  },
  {
    term: 'こそ',
    description: 'precisely, it is ... that',
    examples: ["今日[きょう]こそ行[い]く (today, of all days, I'll go)"],
  },
]

// Attaches to something other than a verb stem, so verb-type conjugation
// doesn't apply either. Examples are shown inline rather than on hover.
export const GRAMMAR_OTHER: GrammarSimpleNote[] = [
  {
    term: 'ない',
    kanjiTerm: '無い',
    description: 'not (after an i-adjective く, or a na-adjective/noun じゃ)',
    examples: [
      'この店[みせ]は高[たか]くない (this store is not expensive)',
      'この部屋[へや]は静[しず]かじゃない (this room is not quiet)',
      '彼[かれ]は学生[がくせい]じゃない (he is not a student)',
    ],
  },
  {
    term: 'する',
    kanjiTerm: '為る',
    description: 'makes the word before it a verb',
    examples: [
      '毎日[まいにち]勉強[べんきょう]する (I study every day)',
      '友達[ともだち]に電話[でんわ]する (I call my friend)',
      '部屋[へや]を掃除[そうじ]する (I clean the room)',
    ],
  },
]

// The term column for any row: kanjiTerm rows show hiragana（kanji）, plain
// rows just show the term. Never wrapped in furigana — see the comment on
// GrammarNote above.
function GrammarTerm({ note }: { note: { term: string; kanjiTerm?: string } }) {
  return (
    <span className="grammar-legend-item-term">
      {note.kanjiTerm ? `${note.term}（${note.kanjiTerm}）` : note.term}
    </span>
  )
}

// A conjugation cell: the form, plus (when present) a hover tooltip with a
// full example sentence and its translation.
function ConjugationCell({ example }: { example: ConjugationExample }) {
  if (!example.sentence) {
    return <span className="grammar-legend-item-example">{example.text}</span>
  }
  return (
    <span className="grammar-legend-item-example grammar-example-hover">
      <Furigana text={example.text} />
      <span className="grammar-example-tooltip">
        <div>
          <Furigana text={example.sentence} />
        </div>
        <div className="grammar-example-tooltip-en">{example.translation}</div>
      </span>
    </span>
  )
}

// A modal listing every grammar word and helper verb from a gloss popup's
// predicate groups, with example conjugations across the three verb
// classes. Escape and the Close button both call onClose.
export function GrammarLegendModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const { dialogRef, hasOpened, onCancel, onClick } = useDialogModal(
    open,
    onClose,
  )

  return (
    <dialog
      ref={dialogRef}
      className="pos-legend-dialog grammar-legend-dialog"
      onCancel={onCancel}
      onClick={onClick}
    >
      {hasOpened && (
        <>
          <div className="pos-legend-title">Grammar Rules</div>

          <div className="grammar-legend-section-title">
            Conjugated with a verb
          </div>
          <div className="grammar-legend-header grammar-legend-row grammar-legend-item">
            <span>Grammar</span>
            <span>Meaning</span>
            <span>Godan (五段)</span>
            <span>Ichidan (一段)</span>
            <span>Irregular (する・来る)</span>
          </div>
          <ul className="pos-legend-list">
            {GRAMMAR_LEGEND.map((note, i) => (
              <li
                key={`${note.term}-${i}`}
                className="grammar-legend-row grammar-legend-item"
              >
                <GrammarTerm note={note} />
                <span className="pos-legend-item-description">
                  {note.description}
                </span>
                <ConjugationCell example={note.godan} />
                <ConjugationCell example={note.ichidan} />
                <ConjugationCell example={note.irregular} />
              </li>
            ))}
          </ul>

          <div className="grammar-legend-section-title">
            Particles that mark a noun, not a verb
          </div>
          <ul className="pos-legend-list">
            {GRAMMAR_NOUN_PARTICLES.map((note, i) => (
              <li
                key={`${note.term}-${i}`}
                className="grammar-legend-row grammar-legend-simple-item"
              >
                <GrammarTerm note={note} />
                <span className="pos-legend-item-description">
                  {note.description}
                </span>
                <span className="pos-legend-item-examples">
                  <FuriganaExampleList examples={note.examples} />
                </span>
              </li>
            ))}
          </ul>

          <div className="grammar-legend-section-title">
            Attaches to something other than a verb
          </div>
          <ul className="pos-legend-list">
            {GRAMMAR_OTHER.map((note, i) => (
              <li
                key={`${note.term}-${i}`}
                className="grammar-legend-row grammar-legend-other-item"
              >
                <GrammarTerm note={note} />
                <span className="pos-legend-item-description">
                  {note.description}
                </span>
                <ul className="grammar-legend-other-examples">
                  {note.examples.map((example, j) => (
                    <li key={j}>
                      <Furigana text={example} />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>

          <div className="pos-legend-dialog-actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
