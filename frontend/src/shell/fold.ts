/** A name as it is looked for: no case, no accents, and Turkish's dotless ı as i - "ilk" finds "İlk deneme". */
export const fold = (text: string) => text.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/ı/g, 'i')
