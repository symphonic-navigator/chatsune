import { safeLocalStorage } from '../../../core/utils/safeStorage'

const KEY = 'chatsune_my_data_last_subpage'

export type MyDataSubpage = 'uploads' | 'artefacts' | 'images'

const VALID: ReadonlyArray<MyDataSubpage> = ['uploads', 'artefacts', 'images']

export function getLastMyDataSubpage(): MyDataSubpage {
  const raw = safeLocalStorage.getItem(KEY)
  if (raw && (VALID as ReadonlyArray<string>).includes(raw)) {
    return raw as MyDataSubpage
  }
  return 'uploads'
}

export function setLastMyDataSubpage(sub: MyDataSubpage): void {
  safeLocalStorage.setItem(KEY, sub)
}
