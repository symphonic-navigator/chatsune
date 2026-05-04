import type { SVGProps } from 'react'

/**
 * Sunglasses glyph — replacement for the 🕶 emoji (incognito chat).
 * Renders at the surrounding font-size and inherits the current text colour.
 * Source: svgrepo.com (sunglasses-2-svgrepo-com.svg).
 */
export function SunglassesIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      width="1em"
      height="1em"
      fill="currentColor"
      aria-hidden="true"
      {...props}
    >
      <path d="M466.141 168.261H277.406s-.078 3.75.188 10.094c-10.109-2.453-12.813-3.797-24.297-3.813-9.484 0-10.266 1.016-18.859 2.688.219-5.641.156-8.969.156-8.969H45.859C20.531 168.261 0 188.792 0 214.12c0 1.828 0 10.563 0 45.813 0 53.938 97.063 113.25 167.172 67.422 44.234-28.922 59.469-84.625 64.703-121.844 8.781-2.484 10.609-4 21.422-4 12.891 0 16.641 2.078 26.422 5.484l.438-1.25c5.266 37.219 20.547 92.766 64.672 121.609 69.109 45.828 166.172-13.484 166.172-67.422 0-35.25 0-43.984 0-45.813 0-25.328-20.531-45.859-45.859-45.859zM32.359 265.323c-7.188-89.875 70.109-70.109 70.109-70.109L32.359 265.323zM328.625 265.323c-7.188-89.875 70.125-70.109 70.125-70.109L328.625 265.323z" />
    </svg>
  )
}
