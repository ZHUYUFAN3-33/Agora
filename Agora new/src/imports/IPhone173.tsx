function Frame() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[#828282] text-[10.61px]">Enter your email...</p>
    </div>
  );
}

function Frame1() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[#828282] text-[10.61px]">Enter your password...</p>
    </div>
  );
}

function Frame2() {
  return (
    <div className="-translate-x-1/2 -translate-y-1/2 absolute bg-black content-stretch flex gap-[10.926px] items-start left-[calc(50%+0.36px)] p-[10.926px] rounded-[10px] top-1/2">
      <p className="font-['Share_Tech_Mono:Regular',sans-serif] leading-[normal] not-italic relative shrink-0 text-[10.61px] text-white">Continue</p>
    </div>
  );
}

function Group() {
  return (
    <div className="absolute contents left-[77px] top-[236px]">
      <div className="absolute bg-black left-[77px] rounded-[5.836px] size-[21.398px] top-[321.59px]" />
      <div className="absolute bg-black left-[164.54px] rounded-[5.836px] size-[21.398px] top-[469.44px]" />
      <div className="absolute bg-black left-[112.02px] rounded-[5.836px] size-[21.398px] top-[440.26px]" />
      <div className="absolute bg-[red] left-[275.42px] rounded-[5.836px] size-[21.398px] top-[440.26px]" />
      <div className="absolute bg-black left-[77px] rounded-[5.836px] size-[21.398px] top-[385.79px]" />
      <div className="absolute bg-black left-[304.6px] rounded-[5.836px] size-[21.398px] top-[323.54px]" />
      <div className="absolute bg-black left-[304.6px] rounded-[5.836px] size-[21.398px] top-[387.74px]" />
      <div className="absolute bg-black left-[112.02px] rounded-[5.836px] size-[21.398px] top-[271.02px]" />
      <div className="absolute bg-black left-[275.42px] rounded-[5.836px] size-[21.398px] top-[271.02px]" />
      <div className="absolute bg-black left-[162.59px] rounded-[5.836px] size-[21.398px] top-[236px]" />
      <div className="absolute bg-black left-[226.79px] rounded-[5.836px] size-[21.398px] top-[236px]" />
      <div className="absolute bg-black left-[228.74px] rounded-[5.836px] size-[21.398px] top-[469.44px]" />
    </div>
  );
}

function Logo() {
  return (
    <div className="absolute contents left-[77px] top-[236px]" data-name="logo">
      <Group />
    </div>
  );
}

export default function IPhone() {
  return (
    <div className="bg-white relative size-full" data-name="iPhone 17 - 3">
      <div className="absolute bg-black h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[666px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame />
      </div>
      <div className="absolute bg-black h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[721px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame1 />
      </div>
      <div className="absolute bg-black h-[40px] left-[75px] shadow-[0px_0px_2.185px_0px_rgba(0,0,0,0.08),0px_1.457px_2.185px_0px_rgba(0,0,0,0.17)] top-[776px] w-[251px]" data-name="Continue with Apple / Centre / Fixed">
        <Frame2 />
      </div>
      <Logo />
    </div>
  );
}