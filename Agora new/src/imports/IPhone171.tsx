function Group() {
  return (
    <div className="absolute contents left-[77px] top-[310px]">
      <div className="absolute bg-black left-[77px] rounded-[5.836px] size-[21.398px] top-[395.59px]" />
      <div className="absolute bg-black left-[164.54px] rounded-[5.836px] size-[21.398px] top-[543.44px]" />
      <div className="absolute bg-black left-[112.02px] rounded-[5.836px] size-[21.398px] top-[514.26px]" />
      <div className="absolute bg-[red] left-[275.42px] rounded-[5.836px] size-[21.398px] top-[514.26px]" />
      <div className="absolute bg-black left-[77px] rounded-[5.836px] size-[21.398px] top-[459.79px]" />
      <div className="absolute bg-black left-[304.6px] rounded-[5.836px] size-[21.398px] top-[397.54px]" />
      <div className="absolute bg-black left-[304.6px] rounded-[5.836px] size-[21.398px] top-[461.74px]" />
      <div className="absolute bg-black left-[112.02px] rounded-[5.836px] size-[21.398px] top-[345.02px]" />
      <div className="absolute bg-black left-[275.42px] rounded-[5.836px] size-[21.398px] top-[345.02px]" />
      <div className="absolute bg-black left-[162.59px] rounded-[5.836px] size-[21.398px] top-[310px]" />
      <div className="absolute bg-black left-[226.79px] rounded-[5.836px] size-[21.398px] top-[310px]" />
      <div className="absolute bg-black left-[228.74px] rounded-[5.836px] size-[21.398px] top-[543.44px]" />
    </div>
  );
}

function Logo() {
  return (
    <div className="absolute contents left-[77px] top-[310px]" data-name="logo">
      <Group />
    </div>
  );
}

export default function IPhone() {
  return (
    <div className="bg-white relative size-full" data-name="iPhone 17 - 1">
      <Logo />
    </div>
  );
}