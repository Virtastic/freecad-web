!     Whole-array reductions that FORTRAN 77 lacks. tools/f77ify.py rewrites
!     maxval(a) and sum(abs(a(:,j))) into these; a column is contiguous, so the
!     second one only ever needs its first element and the row count.
      real*8 function fcwmxv(a,n)
      implicit none
      integer n,i
      real*8 a(*)
      fcwmxv=a(1)
      do i=2,n
         if(a(i).gt.fcwmxv) fcwmxv=a(i)
      enddo
      return
      end
      real*8 function fcwsab(a,n)
      implicit none
      integer n,i
      real*8 a(*)
      fcwsab=0.d0
      do i=1,n
         fcwsab=fcwsab+dabs(a(i))
      enddo
      return
      end
